# E4B Tool-Call LoRA Training Data

**Problem:** Gemma 4 E4B exhibits several tool-call quality issues across all
three agents — premature EOS in write_file (98% truncation rate), malformed
patch arguments, Python syntax hallucinations, and incorrect file paths.

**Fix:** QLoRA fine-tune on repaired examples via mlx-vlm's built-in SFT trainer.
Single adapter deployed to all E4B instances (Boot :41961, Kelk :41962).

## Training Data Summary

| Category | Examples | Source | Priority |
|----------|----------|--------|----------|
| write_file completion | 99 | Kelk sessions — truncated calls repaired from plan text | Critical |
| patch disambiguation | 5 | Boot sessions — "Found 2 matches" errors | High |
| file path correction | 6 | IG-88 sessions — malformed JSON args | Medium |
| Python syntax fix | 1 | IG-88 sessions — escaped triple-quotes | Low |
| **Total** | **111** | | |

**Train/valid split:** 94 / 17 (85/15, seeded shuffle)

## Pipeline

1. `extract_and_repair.py` — extracts raw write_file calls from Kelk sessions
2. `extract_training_data.py` — extracts patch/syntax/path errors from all agents
3. `generate_repaired.py` — completes truncated writes using plan text (Opus)
4. Merge script (inline) — combines all JSONL, shuffles, splits 85/15
5. **Train:** `python3 -m mlx_vlm trainer sft --model /Users/nesbitt/models/gemma-4-e4b-it-6bit --data training/kelk-write-fix/train.jsonl --adapter-path training/kelk-write-fix/e4b-adapter --iters 200 --batch-size 1 --learning-rate 1e-5`
6. **Deploy:** Add `--adapter-path training/kelk-write-fix/e4b-adapter` to mlx-vlm plist ProgramArguments

## Files

- `raw_extracts.jsonl` — 151 raw write_file calls (148 truncated, 3 complete)
- `repaired_write_file.jsonl` — 99 completed write_file examples (248KB)
- `repaired_patch.jsonl` — 5 patch disambiguation examples
- `repaired_syntax.jsonl` — 1 Python syntax fix
- `repaired_paths.jsonl` — 6 file path corrections
- `train.jsonl` — 94 training examples (merged, shuffled)
- `valid.jsonl` — 17 validation examples
- `e4b-adapter/` — trained LoRA weights (TBD — run training step)

## Training Command (when ready)

```bash
# Shut down Boot+Kelk MLX first (frees ~13GB for training)
# Training takes ~2-3h on M1 Max 32GB

/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3 -m mlx_vlm trainer sft \
  --model /Users/nesbitt/models/gemma-4-e4b-it-6bit \
  --data /Users/nesbitt/dev/factory/training/kelk-write-fix/train.jsonl \
  --adapter-path /Users/nesbitt/dev/factory/training/kelk-write-fix/e4b-adapter \
  --iters 200 \
  --batch-size 1 \
  --learning-rate 1e-5
```

## Deployment

Add to Boot and Kelk MLX plists:
```xml
<string>--adapter-path</string>
<string>/Users/nesbitt/dev/factory/training/kelk-write-fix/e4b-adapter</string>
```
