# FCT093 — Coord Aux Deprecation and E4B Wrapper Limit Bump

**Date:** 2026-05-02
**Status:** In progress (file edits complete; Boot/Kelk restarts pending operator approval)
**Supersedes:** FCT092 §"Hermes wiring (post-deploy)" routing to :41963
**Depends on:** FCT078 (mlx-lm wrapper), FCT091 (E4B-SABER production selection), FCT092 (Coord aux tier)

---

## Summary

The E2B-SABER Coord aux tier (FCT092, :41963) is deprecated. Its ~6 GB wired allocation is reclaimed and split between the two E4B-SABER primary instances (Boot + Kelk), whose `mlx-lm-factory-wrapper.py` Metal/wired limits are bumped from 10 GB → 12 GB each. All Hermes aux slots that were routed to :41963 (compression, summary) are folded back into the agent's primary E4B endpoint.

Net effect:
- One fewer model server to keep healthy
- ~2 GB more wired headroom per E4B (deeper prompt cache, less KV eviction at long context)
- ~2 GB freed for OS + Hermes + MCP overall (~8 GB headroom vs ~6 GB tri-server)

---

## Why deprecate Coord

The Coord aux tier passed all four agentic gates (FCT092) and was technically valuable for bounded subroutines. Operator preference is to consolidate on dual E4B for simpler operations and to redirect the freed memory toward making the E4Bs more reliable under real Matrix workloads. Coord ran for hours under the tri-server topology without measurable issues, but its actual production value was speculative — Hermes never had time to develop call patterns that exercised the aux tier as designed.

The model file (`~/models/Gemma-4-E2B-SABER-MLX-6bit/`) and HF source (`~/models/Gemma-4-E2B-SABER-HF/`) are preserved on disk. The plist is renamed `.deprecated`. Reactivation is one `mv` + `launchctl bootstrap` away if a future workload genuinely needs it.

---

## Wrapper memory bump

`scripts/mlx-lm-factory-wrapper.py` constants:

```
- METAL_LIMIT_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
- WIRED_LIMIT_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
+ METAL_LIMIT_BYTES = 12 * 1024 * 1024 * 1024  # 12 GB (FCT093)
+ WIRED_LIMIT_BYTES = 12 * 1024 * 1024 * 1024  # 12 GB (FCT093)
```

Two measurable benefits:

1. **Larger prompt-cache footprint.** The wired limit caps how much KV cache MLX keeps resident before eviction. At 10 GB on a 96K-declared context, long Matrix conversations (say, 30K+ tokens of accumulated history) were hitting eviction, forcing cold prefill on the next turn. 12 GB lets the cache stay resident for typical conversation depths → lower TTFT on multi-turn dialogues.
2. **Headroom for dual concurrent inference.** When Boot and Kelk both fire at once (operator + autonomous task), each peaks at the wired limit. With only the E4Bs running, 2× 12 GB = 24 GB; OS + Hermes + MCP fit in the remaining ~8 GB. With Coord still up at ~6 GB, this would not be possible — the freed memory is exactly what enables the bump.

The wrapper is shared by both Boot and Kelk plists, so the bump applies to both at the next plist restart. No per-plist configuration needed.

---

## Hermes config changes

In both `~/.hermes/profiles/{boot,kelk}/config.yaml`:

| Slot | Was (FCT092) | Now (FCT093) |
|------|--------------|--------------|
| `auxiliary.compression.base_url` | `http://127.0.0.1:41963/v1` | `http://127.0.0.1:41961/v1` (Boot) / `:41962` (Kelk) |
| `auxiliary.compression.model` | `Gemma-4-E2B-SABER-MLX-6bit` | `Gemma-4-E4B-SABER-MLX-6bit` |
| `auxiliary.compression.summary_*` | E2B Coord | Same primary E4B |
| `custom_providers[1]` | `local-mlx-coord` (E2B :41963) | **REMOVED** (duplicate of `local-mlx`) |
| `providers.local-mlx-coord` | E2B :41963 | **REMOVED** (duplicate of `local-mlx`) |

All other settings carried forward from FCT092: `context_length: 98304` (96K), `compression.threshold: 0.67`, `agent.max_turns: 48`, `tool_use_enforcement: none`, `approvals.mode: deny`, `vision` slot removed.

---

## What to do if performance regresses

If E4B latency or coherence gets *worse* after this change (against expectation), the most likely cause is that compaction quality degraded — E2B did the compaction differently and the E4B's compaction summary may eat more context than E2B's did. Mitigations in order:

1. **Lower `compression.threshold` from 0.67 → 0.5** to compact earlier with smaller summaries.
2. **Reduce `max_tokens` from 8192 → 4096** for compaction calls if summaries are runaway.
3. **Re-enable Coord** by reversing the deprecation (one `mv` + `launchctl bootstrap`) and reverting the Hermes compression slot to :41963.

---

## Restart sequence (operator-approved)

```
# 1. Stop Coord (already done as part of this sprint)
launchctl bootout gui/$(id -u)/com.bootindustries.mlx-lm-factory-coord
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist \
   ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist.deprecated

# 2. Restart mlx-lm-factory-{boot,kelk} to pick up 12 GB wrapper limits
#    Stagger: do Boot first, verify Boot UP, then Kelk
launchctl bootout gui/$(id -u)/com.bootindustries.mlx-lm-factory-boot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-boot.plist
# wait for :41961 healthy
launchctl bootout gui/$(id -u)/com.bootindustries.mlx-lm-factory-kelk
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-kelk.plist
# wait for :41962 healthy

# 3. Restart hermes-{boot,kelk} to pick up new compression routing
launchctl bootout gui/$(id -u)/com.bootindustries.hermes-boot
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.hermes-boot.plist
launchctl bootout gui/$(id -u)/com.bootindustries.hermes-kelk
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.hermes-kelk.plist
```

Total downtime per agent ≈ 25–30 s during its own restart window. Boot and Kelk restarts can be staggered so at no point are both agents simultaneously down.

---

## Rollback (if FCT093 turns out to be regressive)

```
# 1. Revert wrapper limits
sed -i '' 's|12 \* 1024 \* 1024 \* 1024  # 12 GB|10 * 1024 * 1024 * 1024  # 10 GB|g' \
  /Users/nesbitt/dev/factory/scripts/mlx-lm-factory-wrapper.py

# 2. Re-enable Coord plist
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist.deprecated \
   ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist

# 3. Restore Hermes compression routing to :41963 (see FCT092 §Hermes wiring)
# 4. Restart all three plists + both Hermes gateways
```

---

## Verification

- `:41963` returns connection refused (deprecated plist not loaded)
- `:41961` + `:41962` return their E4B-SABER model on `/v1/models`
- `factory-status.sh` shows two model servers, no `:41963` reference
- `factory-startup.sh` Phase 1 brings up only Boot + Kelk, requires 24 GB free
- After plist restart: each E4B wrapper log shows `Metal limit: 12 GB` and `Wired limit: 12 GB`

---

## Related

- FCT091 — E4B-SABER selection
- FCT092 — Coord aux tier (now superseded for primary topology)
- FCT078 — mlx-lm wrapper architecture
