# Ornstein3.6-35B-A3B C/Metal Debug Handoff

## Status: WORKING (7.2 tok/s, coherent output with reasoning)

## Fix Summary
Three critical bugs fixed:
1. **NUM_EXPERTS_PER_TOK 4→8** (config says 8, not 4)
2. **Chat template missing `<think>\n`** (Qwen3.6 thinking mode requires it)
3. **8-bit gate scores computed on CPU** (GPU 8-bit kernel produces wrong results — flash-moe issue #10)

The fix for #3 was found by studying Ma-Dan's working fork:
https://github.com/Ma-Dan/flash-moe/tree/Qwen3.6-35B-A3B

Ma-Dan's approach: after GPU batch matvec, override gate and shared_expert_gate
scores on CPU using `cpu_dequant_matvec_8bit`. The GPU 8-bit dequant kernel
produces wrong routing scores, selecting wrong experts every layer.

## Key Changes in infer_35b.m
- Line 80: `#define NUM_EXPERTS_PER_TOK 8` (was 4)
- Line 6595: `int K = 8;` (was 4)
- Lines 5029-5034: BatchMatvecSpec `bits=8` for gate_w and seg_w
- Lines 5078-5083: Same fix for CPU fallback path
- Line 5091-5094: CPU override of gate/shared_expert_gate after GPU matvec
- Lines 5978, 5916, 5934: Chat template includes `<think>\n`

## Test Command
```bash
cd /Users/nesbitt/dev/vendor/flash-moe/metal_infer
./infer_35b \
  --weights /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/model_weights.bin \
  --manifest /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/model_weights.json \
  --vocab /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/vocab.bin \
  --prompt "What is 2+2?" --tokens 200
```

## Output Sample
```
Thinking Process: 
1. Analyze the input: The user is asking a simple arithmetic question "What is 2+2?"
2. Identify the operation: Addition of two integers
3. Perform the calculation: 2 + 2 = 4
4. Verify the answer: This is a basic arithmetic fact that can be confirmed
5. Formulate the response: State the answer clearly

The answer is 4.
```
~7.2 tok/s on M1 Max 32GB

## Remaining Work
1. Remove debug prints (327 printf statements)
2. Clean up `--serve` HTTP server for Hermes integration
3. Deploy as production service on :41961
4. The `FLASHMOE_FORCE_CPU` env var can be removed (was debug-only)

## Lesson Learned
Community knowledge is valuable. The flash-moe GitHub issues (#10, #20)
and Ma-Dan's fork contained the exact fix we needed. Always check external
resources before debugging in isolation.
