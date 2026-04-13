# FCT066 E4B LoRA Training Pipeline — Tool-Call Quality Fix

**Date:** 2026-04-12
**Author:** Chris (operator guide)
**Status:** Ready to execute

---

## Purpose

Gemma 4 E4B (12B total, 4B active MoE) running as Boot (`:41961`) and Kelk (`:41962`) on Whitebox exhibits premature EOS during `write_file` tool call argument generation. Approximately 98% of Kelk's `write_file` calls produce empty content. This LoRA adapter fixes the behavior using 111 repaired training examples extracted from agent session history.

The adapter is a single LoRA that deploys to all E4B instances -- both Boot and Kelk benefit from the same weights.

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Free memory | Both Boot (`:41961`) and Kelk (`:41962`) MLX servers must be shut down before training (frees ~13GB for training overhead) |
| IG-88 | No action needed -- runs on OpenRouter, no local MLX dependency |
| Training data | `training/kelk-write-fix/train.jsonl` (94 examples), `valid.jsonl` (17 examples) |
| Python env | `/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3` (mlx-vlm with trainer module) |
| Base model | `/Users/nesbitt/models/gemma-4-e4b-it-6bit` (6-bit quantized, QLoRA compatible) |

---

## Step 1: Shut Down E4B Servers

Stop both agent inference servers and wait for full memory release.

```bash
launchctl bootout gui/$(id -u)/com.bootindustries.mlx-vlm-boot
launchctl bootout gui/$(id -u)/com.bootindustries.mlx-vlm-kelk
rm ~/Library/LaunchAgents/com.bootindustries.mlx-vlm-boot.plist
rm ~/Library/LaunchAgents/com.bootindustries.mlx-vlm-kelk.plist
pkill -f "mlx_vlm.server" 2>/dev/null
# Wait for processes to fully exit
while pgrep -f "mlx_vlm.server" >/dev/null 2>&1; do sleep 2; done
echo "Memory freed"
```

---

## Step 2: Run Training

Training uses QLoRA directly on the 6-bit quantized model -- no BF16 download needed.

```bash
cd ~/dev/factory

/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3 -m mlx_vlm trainer sft \
  --model /Users/nesbitt/models/gemma-4-e4b-it-6bit \
  --data /Users/nesbitt/dev/factory/training/kelk-write-fix/train.jsonl \
  --adapter-path /Users/nesbitt/dev/factory/training/kelk-write-fix/e4b-adapter \
  --iters 200 \
  --batch-size 1 \
  --learning-rate 1e-5
```

**Expected duration:** ~2-3 hours on M2 Max 32GB. Loss should decrease steadily. If it plateaus early, extend iterations to 300.

---

## Step 3: Validate (Smoke Test)

After training completes, test the adapter before deploying to production.

**Start a test server with the adapter loaded:**

```bash
/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3 -m mlx_vlm.server \
  --model /Users/nesbitt/models/gemma-4-e4b-it-6bit \
  --adapter-path /Users/nesbitt/dev/factory/training/kelk-write-fix/e4b-adapter \
  --host 127.0.0.1 --port 41966
```

**In another terminal, send a write_file test prompt:**

```bash
curl -s http://127.0.0.1:41966/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma-4-e4b-it-6bit", "messages": [{"role": "user", "content": "Write a 200-word markdown document about the Ichimoku cloud trading strategy to /tmp/test.md"}], "max_tokens": 2048}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'][:500])"
```

**Pass criteria:** The response contains a complete `write_file` tool call with substantial content (>100 words). If the content field is empty or truncated, the adapter needs more training iterations.

---

## Step 4: Deploy

Add `--adapter-path` to both Boot and Kelk plists, then bootstrap the services.

Edit each plist to add these two lines to `ProgramArguments` (before `</array>`):

```xml
<string>--adapter-path</string>
<string>/Users/nesbitt/dev/factory/training/kelk-write-fix/e4b-adapter</string>
```

Then install and start:

```bash
cp ~/dev/factory/plists/com.bootindustries.mlx-vlm-boot.plist ~/Library/LaunchAgents/
cp ~/dev/factory/plists/com.bootindustries.mlx-vlm-kelk.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-vlm-boot.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-vlm-kelk.plist
```

---

## Step 5: Verify in Production

Start an `h-kelk` session and ask Kelk to write a document. The `write_file` tool call should now produce complete content instead of empty strings.

Check a few different content types (markdown, code, config files) to confirm the fix generalizes beyond the training distribution.

---

## Rollback

If the adapter degrades other behaviors, remove the `--adapter-path` lines from the plists and restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.bootindustries.mlx-vlm-boot
launchctl kickstart -k gui/$(id -u)/com.bootindustries.mlx-vlm-kelk
```

This restarts with the base model only, reverting to pre-adapter behavior.

---

## Training Data Composition

| Category | Count | Source |
|----------|-------|--------|
| write_file completion | 99 | Kelk sessions -- plan text to completed content |
| patch disambiguation | 5 | Boot sessions -- "Found 2 matches" errors |
| file path correction | 6 | IG-88 sessions -- malformed JSON args |
| Python syntax fix | 1 | IG-88 sessions -- escaped triple-quotes |
| **Total** | **111** | 94 train / 17 valid |

---

## Notes

- The adapter weights are typically 50-200MB, much smaller than the 7GB base model
- If you add more training data later, append to `train.jsonl` and rerun Step 2 with `--resume-adapter-file` to continue training from the existing checkpoint
- Port `:41966` is the designated validation/test slot for MLX inference (see `infra/ports.csv`)
