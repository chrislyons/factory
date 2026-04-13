# Kelk Write-File LoRA Training Data

**Problem:** Gemma 4 E4B emits premature EOS tokens during `write_file` tool call
argument generation. 98% of Kelk's write_file calls produce empty or near-empty
content despite the model planning full documents in its response text.

**Evidence:** 151 write_file calls extracted from 27 Kelk sessions. 148 truncated
(98%), 3 complete. 144 truncated calls have recoverable plan text showing the
model's intent.

**Fix:** QLoRA fine-tune on repaired examples — complete write_file calls with
full content matching the plan. Trains the model to sustain generation through
the tool call argument without premature EOS.

## Pipeline

1. `extract_and_repair.py` — extracts raw write_file calls from Kelk sessions
2. `repair_examples.py` — completes truncated writes using plan text (manual/Opus)
3. `build_training_jsonl.py` — formats repaired examples into mlx-vlm SFT format
4. Train: `mlx_vlm.trainer.sft_trainer` on 6-bit E4B with QLoRA
5. Deploy: `mlx-vlm --model E4B --adapter-path ./kelk-adapter` on :41962

## Files

- `raw_extracts.jsonl` — 151 raw write_file calls (148 truncated, 3 complete)
- `repaired_examples.jsonl` — completed writes (TBD)
- `train.jsonl` / `valid.jsonl` — training data in mlx-vlm format (TBD)
- `kelk-adapter/` — trained LoRA weights (TBD)

## Stats

- Sessions scanned: 27
- Total write_file calls: 151
- Truncated: 148 (98%)
- Recoverable (has plan text): 144
- Target training examples: 100+
