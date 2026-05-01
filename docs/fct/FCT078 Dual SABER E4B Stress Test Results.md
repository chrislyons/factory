# FCT078 Dual SABER E4B Stress Test Results

**Date:** 2026-04-30
**Machine:** Whitebox (Mac Studio M1 Max, 32GB unified memory)
**Model:** Gemma-4-E4B-SABER-MLX-6bit (~6GB weights)
**Server:** mlx-lm 0.31.3, `--prompt-cache-bytes 4294967296` (4GB cap per server, tested up to concurrent 25K-token input)
**Ports:** :41961 (Boot), :41962 (Kelk)

## Context

Previous dual-SABER setup crashed repeatedly due to:
- flash-moe-ornstein (:41966) consuming GPU memory simultaneously
- mlx-vlm duplicate services on same ports
- No prompt cache caps

This test validates dual SABERs in isolation with 2GB cache caps.

## Test 1: Single Server Baseline (SABER on :41961 only, 6GB cap)

| Request | Prompt tok | Output tok | tok/s | Peak wired |
|---------|-----------|------------|-------|------------|
| Short (512 out) | 36 | 512 | 34.0 | — |
| Long (2048 out) | 134 | 2048 | 33.6 | — |

Sustained single-server stress (3 sequential requests):
- Wired peaked at 9.6GB, plateaued after first request
- RSS held at 6.3GB throughout

## Test 2: Concurrent Dual-Server (2GB caps)

Both servers hit simultaneously with 4096-token generation requests.

| Sample | Wired | Boot RSS | Kelk RSS | Free |
|--------|-------|----------|----------|------|
| Before | 2.7 GB | 6.25 GB | 6.25 GB | 1.5 GB |
| t=15s | 16 GB | 6.26 GB | 6.26 GB | 147 MB |
| t=30s | 16 GB | 6.26 GB | 6.26 GB | 122 MB |
| t=45s | 16 GB | 6.26 GB | 6.26 GB | 340 MB |
| t=60s | 16 GB | 6.26 GB | 6.26 GB | 349 MB |
| t=75s | 16 GB | 6.26 GB | 6.26 GB | 256 MB |
| t=90s | 16 GB | 6.26 GB | 6.26 GB | 233 MB |
| t=105s | 16 GB | 6.26 GB | 6.26 GB | 226 MB |
| t=120s | 9.5 GB | 6.26 GB | 6.26 GB | 219 MB |

**Result:** RSS flat. Wired peaked at 16GB during concurrent inference. No crash. No OOM.

## Test 3: Multi-turn sustained load (pending)

## Test 4: Long-context stress (pending)

## Test 5: Extended soak (pending)

## flash-moe Comparison

| Model | tok/s | Resident mem | Stability |
|-------|-------|-------------|-----------|
| SABER E4B 6-bit | 34.0 | ~6.2 GB | Stable |
| Ornstein 35B-A3B flash-moe | ~5.5 | ~5 GB | Crashed at 320 tok |

## Conclusions (pending full test)


## Test 3: Multi-turn sustained load (2GB caps)

Sequential 3-turn conversation on :41961 (building context), then concurrent burst on both ports.

| Phase | Wired | RSS (each) | Free |
|-------|-------|-----------|------|
| Before | 2.7 GB | 6.25 GB | 1.9 GB |
| After turn 1 (:41961) | 9.4 GB | 6.26 GB | 1.1 GB |
| After turn 2 (:41961) | 9.9 GB | 6.26 GB | 166 MB |
| After turn 3 (:41961) | 10 GB | 6.26 GB | 169 MB |
| After concurrent burst | 17 GB | 6.26 GB | 115 MB |

**Result:** RSS flat at 6.26GB per server throughout. Wired peaked at 17GB during concurrent inference. No crash, no OOM. Cache cap likely not even reached — servers staying at baseline.

## Test 4: Concurrent + multi-turn (4GB caps)

Same tests as 2/3 but with 4GB prompt-cache-bytes per server.

### Concurrent 4096-token burst:

| Sample | Wired | Boot RSS | Kelk RSS | Free |
|--------|-------|----------|----------|------|
| Before | 2.7 GB | 6.26 GB | 6.25 GB | 2.5 GB |
| t=15s | 16 GB | 6.27 GB | 6.26 GB | 551 MB |
| t=30s | 16 GB | 6.27 GB | 6.26 GB | 578 MB |
| t=60s | 16 GB | 6.27 GB | 6.26 GB | 522 MB |
| t=105s | 16 GB | 6.27 GB | 6.26 GB | 572 MB |
| After | 2.7 GB | 6.27 GB | 6.26 GB | 1.4 GB |

### Multi-turn concurrent (3 turns, both ports):

| Phase | Wired | Boot RSS | Kelk RSS | Free |
|-------|-------|----------|----------|------|
| After turn 1 | 15 GB | 6.27 GB | 6.27 GB | 361 MB |
| After turn 2 | 9.7 GB | 6.27 GB | 6.27 GB | 408 MB |
| After turn 3 | 9.7 GB | 6.27 GB | 6.27 GB | 160 MB |

**Result:** Identical behavior to 2GB caps. RSS flat at 6.27GB per server. Cache cap not reached. 4GB caps are safe.

## Test 5: Hermes-scale context tests (4GB caps)

### 5a: Single server, ~5K token input (:41961 only)

| Metric | Value |
|--------|-------|
| Input tokens | 4,964 |
| Output tokens | 2,683 |
| Decode tok/s | 29.1 |
| Boot RSS delta | +3 MB |
| Wired peak | 10 GB |
| Free trough | 717 MB |

### 5b: Single server, ~25K token input (:41961 only)

| Metric | Value |
|--------|-------|
| Input tokens | 24,728 |
| Output tokens | 1,984 |
| Decode tok/s | 16.2 |
| Boot RSS delta | +6 MB |
| Wired peak | 11 GB |
| Free trough | 86 MB |

### 5c: CONCURRENT ~25K token input (both ports)

| Metric | Value |
|--------|-------|
| Wired peak | 20 GB |
| Free trough | 71 MB |
| Boot RSS | flat 6.28 GB → 6.14 GB |
| Kelk RSS | flat 6.28 GB → 6.15 GB |
| Compressor | 227 MB → 386 MB |
| Crash? | **No** |

Free dropped to 71MB during concurrent 25K-token inference but macOS managed pressure gracefully via inactive page reclamation and minor compression. No swap storm, no crash, no beachball.

## Conclusions

### Architecture: Dual SABER E4B (shared model, separate ports)

| Config | Value |
|--------|-------|
| Model | Gemma-4-E4B-SABER-MLX-6bit (~6GB weights) |
| Boot | :41961 via com.bootindustries.mlx-lm-factory-boot |
| Kelk | :41962 via com.bootindustries.mlx-lm-factory-kelk |
| Cache cap | 4GB per server (--prompt-cache-bytes 4294967296) |
| Peak RSS per server | ~6.3 GB (flat under all tests) |
| Peak wired (concurrent) | 20 GB |
| Tok/s (short context) | 34.0 |
| Tok/s (25K context) | 16.2 |

### What was retired

| Service | Reason |
|---------|--------|
| flash-moe-ornstein (:41966) | 35B model exceeded 32GB unified memory, caused GPU abort crashes |
| mlx-vlm-boot/kelk/whitebox | Duplicate services conflicting on same ports |
| mlx-lm-boot/kelk (per-agent) | Replaced by factory-boot/factory-kelk naming |

### Risk assessment

- **Normal agent sessions (5-15K tokens):** Safe, plenty of headroom
- **Heavy concurrent sessions (25K+ tokens):** Survivable but tight (~71MB free)
- **Failure mode:** macOS compressor + inactive reclamation handles pressure gracefully; no OOM observed
- **Monitoring:** Watch Activity Monitor "Memory Pressure" gauge; if it stays green/yellow, system is healthy

### Pending

- [ ] Live Matrix agent test validation
- [ ] Extended soak test (hours of real agent use)
