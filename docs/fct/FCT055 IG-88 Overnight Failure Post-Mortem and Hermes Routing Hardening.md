# FCT055 — IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening

**Date:** 2026-04-08
**Status:** Investigation complete; remediation plan pending approval
**Scope:** IG-88 first-autonomy-night failure, Hermes provider routing audit, coordinator Hermes HTTP client review, port and plist hygiene
**Related:** FCT046 (Provider Failover Chain), FCT047 (Hermes Phase 3), FCT052 (Hermes Phase 4 HTTP Daemon), FCT053 (Matrix Dual-Login), FCT054 (Local E4B Consolidation)

## 1. TL;DR

On the night of 2026-04-07→08, Chris assigned IG-88 its first autonomous self-development session (backtest and paper-trade infrastructure validation). IG-88 failed to complete the work, repeatedly timing out with malformed tool calls, memory corruption, and eventually hitting Hermes's 600-second hard agent-execution ceiling at 03:01 UTC.

Four distinct failure modes stacked on the same night:

1. **Path typo in the handoff prompt** — Chris's prompt used `~/factory/...` instead of `~/dev/factory/...`. IG-88 (a 4B local model) had no way to recover and spent the early hours failing every file read and corrupting its memory with garbled path-correction tool calls.
2. **Provider routing bug (self-inflicted, mid-session fix)** — The IG-88 Hermes profile initially lacked `provider: custom`. With `OPENROUTER_API_KEY` injected by Infisical, Hermes's `runtime_provider.py` normalized requests to OpenRouter and sent the local filesystem path `/Users/nesbitt/models/gemma-4-e4b-it-6bit` as the `model` parameter → HTTP 400. Fixed in-session at ~01:34.
3. **matrix-nio dependency missing at restart** — When IG-88's gateway bounced to pick up FCT054's config changes, `matrix-nio` was not installed in the hermes-agent venv. Launchd KeepAlive respawned the gateway into the same failure for ~30 seconds until the dep was present.
4. **600-second tool-call dead-loop** — Once the gateway was stable and the provider was pinned to local MLX, Gemma 4 E4B emitted malformed tool calls (`<|tool_call>call:search_files{...}`, `memory: "~memory: ..."`) that Hermes couldn't parse. The model retried in a dead loop until Hermes's 600s agent execution ceiling fired.

None of these were port contention. Runtime port state is clean. Server↔client port mappings all match FCT054.

Two separate classes of latent bug were also surfaced during the investigation and are tracked here:

- **Coordinator Hermes HTTP client bugs** — affect Boot/Kelk (coordinator-dispatched), **not** IG-88 (standalone gateway). `coordinator/src/agent.rs:395` passes the profile name as the model ID. `coordinator/src/hermes_adapter.rs:140-143` extracts only `content` and drops the `tool_calls` array.
- **Plist and port-scheme drift** — Five stale `com.bootindustries.mlx-lm-*.plist` files remain at `~/Library/LaunchAgents/`. `infra/ports.csv` describes the pre-FCT054 world.

## 2. Architecture Reminder (so we don't fight the shape)

IG-88 and Boot/Kelk use deliberately different Hermes wiring. This is not a bug:

| Agent | Runtime mode | Matrix adapter | Backend | Ports |
|-------|--------------|----------------|---------|-------|
| IG-88 | Standalone Hermes gateway | matrix-nio (native, direct to Pantalaimon) | mlx-vlm-ig88 (dedicated) | :41988 |
| Boot | Coordinator-dispatched Hermes HTTP daemon | Coordinator's matrix_legacy.rs | mlx-vlm-factory (shared) | :41970 → :41961 |
| Kelk | Coordinator-dispatched Hermes HTTP daemon | Coordinator's matrix_legacy.rs | mlx-vlm-factory (shared) | :41972 → :41961 |

IG-88's standalone path is deliberate: it runs autonomous scan loops and heavy tool sessions that should not compete with Chris's interactive DMs to Boot/Kelk on the coordinator event loop, and it benefits from Hermes's native gateway allowlists (`GATEWAY_ALLOWED_USERS=@chrislyons:matrix.org`, `unauthorized_dm_behavior: ignore`) without reimplementing them in Rust.

**Therefore the coordinator-side Hermes bugs in §5 do not explain IG-88's overnight failure.** They explain future Boot/Kelk pain and are tracked here for follow-up.

## 3. Forensic Timeline — IG-88, 2026-04-07 → 2026-04-08

Source: `~/.hermes/profiles/ig88/logs/errors.log`, `~/.hermes/profiles/ig88/sessions/request_dump_*.json`, `~/Library/Logs/factory/hermes-ig88.log`, `~/Library/Logs/factory/mlx-vlm-ig88.log`.

| Time (local) | Event | Interpretation |
|---|---|---|
| 12:24, 12:45, 20:36 | OpenRouter HTTP 404 "No endpoints found that support tool use. Try disabling browser_back" | IG-88 was still cloud-routed earlier in the day; the tool advertised exceeded what any OpenRouter backing model supported. Not last night's cause, but shows IG-88 had been cloud-bound pre-FCT054 cutover. |
| 21:23 | HTTP 400 on a different cloud model ID | Continued cloud routing attempts with bad IDs. |
| 00:32:28, 00:32:43, 00:32:59 | `gateway.platforms.matrix: matrix-nio not installed`, `Gateway failed to connect any configured messaging platform` (×3) | FCT054 cutover restart, hermes-agent venv missing matrix-nio dependency. Launchd KeepAlive respawned the process three times across 30 seconds until dep was present. |
| 00:46, 00:56 | `Unauthorized user: @coord:matrix.org` warnings | Coordinator was still trying to DM IG-88; gateway correctly dropped those (allowlist working). |
| 01:32:25 | `HTTP 400: /Users/nesbitt/models/gemma-4-e4b-it-6bit is not a valid model ID` | **The provider routing bug.** Profile did not yet have `provider: custom`. Hermes's runtime_provider.py saw `OPENROUTER_API_KEY` in env (injected by Infisical via `hermes-ig88.sh` lines 42-43), normalized `requested_provider="openrouter"`, ignored the `base_url: http://127.0.0.1:41988/v1`, and sent the local filesystem path as a model ID to `https://openrouter.ai/api/v1/chat/completions`. The user_id in the response body confirms OpenRouter was the actual recipient. |
| 01:34:52 | Same HTTP 400 | Second occurrence before the fix landed. |
| 01:34:52+ | No further 400s | `provider: custom` was added to `~/.hermes/profiles/ig88/config.yaml` line 8. Routing to local :41988 restored. |
| 03:01:06 | `Agent execution timed out after 600s for session agent:main:matrix:dm:!...:matrix.org` | **The overnight death.** Local inference was working — but Gemma 4 E4B was emitting malformed tool calls the Hermes parser couldn't process, retrying in a dead loop until the 600s hard ceiling fired. |

The coordinator-ingested transcript Chris saved shows the rest of the degradation pattern: tool calls leaking as text (`<|tool_call>call:search_files{...}`, `memory: "~memory: \"The primary project\""`), `ReadTimeout` reconnect attempts from the mcp.client side during the dead-loop, and an eventual "Request timed out after 10 minutes" message in the Matrix room.

## 4. Root Causes, by Rank

### RC-1 — Provider routing precedence in `runtime_provider.py` (fixed in-session)

**Location:** `/Users/nesbitt/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/hermes_cli/runtime_provider.py:340–389`

**The gate:**
```python
if requested_norm == "auto":
    if not cfg_provider or cfg_provider == "auto":
        use_config_base_url = True
elif requested_norm == "custom" and cfg_provider == "custom":
    use_config_base_url = True
```

The `base_url` is only honored when both requested and config provider resolve to `"custom"`. If `OPENROUTER_API_KEY` is in env and the config does not pin `provider: custom`, `requested_norm` auto-resolves to `"openrouter"` and the `base_url` is silently dropped. The `model` field (which for local inference is a filesystem path) is then forwarded to OpenRouter verbatim.

**Current state:** `provider: custom` is present in all three profiles (`ig88`, `boot`, `kelk`). Verified by direct read.

**Remaining risk:** This is an unstable defense. Any future profile that omits `provider: custom` will silently cloud-route as soon as `OPENROUTER_API_KEY` is in env. The defense needs to be structural, not per-profile discipline.

### RC-2 — Gemma 4 E4B tool-call format mismatch (root of the 600s dead-loop)

**Upstream Hermes behavior** (confirmed via https://hermes-agent.nousresearch.com/docs/integrations/providers): Hermes expects native OpenAI `tool_calls` JSON over the wire. It does not parse `<tool_call>` / `<|tool_call|>` tokens client-side. For self-hosted backends, the server is responsible for translating the model's native tool-use format into OpenAI-compatible `tool_calls`.

- **vLLM** does this with `--enable-auto-tool-choice --tool-call-parser hermes`.
- **llama.cpp** does this with `--jinja` flag (the docs warn that without `--jinja`, "llama-server ignores the `tools` parameter entirely. The model will try to call tools by writing JSON in its response text.").
- **mlx_vlm** has no documented equivalent flag.

**Consequence:** mlx_vlm is not translating Gemma's native tool-use tokens into OpenAI-compatible `tool_calls`. Gemma 4 E4B is emitting tool calls as raw text (`<|tool_call>call:search_files{...}`, `memory: "~memory: ..."`), Hermes is treating those as assistant text, and the model is re-emitting them in an infinite "I just tried to call the tool, let me try again" loop until the 600s ceiling fires.

**The factory-size factor:** 4B-class models are on the edge of reliable tool use even with correct parser wiring. Gemma 4 E4B in 6-bit quant is below the reliability floor Hermes's docs implicitly assume. Upstream docs contain zero guidance on 4B-class tool reliability; this is a known gap.

**This is the dominant overnight failure.** Even a perfectly configured routing stack will not fix this — the model is physically not emitting parseable tool calls.

### RC-3 — Path typo in the handoff prompt

**Origin:** The original Matrix DM from Chris to IG-88 used `~/factory/agents/ig88/...`. The correct path is `~/dev/factory/agents/ig88/...`. The typo was corrected mid-session but only after IG-88 had failed every file read and polluted its working memory with invalid paths.

**Why this was catastrophic for a 4B model:** Gemma 4 E4B could not disambiguate "file doesn't exist" from "tool call was malformed" and blended the two failure modes. It also emitted a memory-write tool call that wrote an empty value (`memory: "~memory: \"The primary project\""` — truncated mid-edit), which means the memory file is now in a partially-corrupted state.

**Already captured as durable feedback:** `~/.claude/projects/-Users-nesbitt-dev-factory/memory/feedback_agent_handoff_accuracy.md`.

### RC-4 — matrix-nio dependency gap at FCT054 cutover

Between 00:32 and 00:33, `hermes-ig88` launchd-bounced three times with `matrix-nio not installed`. This is transient (self-resolved within 30s when the dep was present), but the FCT054 rollout did not explicitly verify gateway dependencies before restarting the service. Cutover smoke test failed silently under KeepAlive.

### RC-5 — Hermes gateway has no inference-level HTTP timeout

Per the Hermes docs audit: the primary inference HTTP client has **no documented timeout**. The only enforcement is the 600s agent-execution ceiling that fired at 03:01. This means a stuck inference request can consume the full 600s before the gateway gives up, and there's no faster path to detect-and-recover.

### RC-6 — No fallback_providers on IG-88 profile

`fallback_providers: []` means that when local inference stalls or returns bad output, there's no escape hatch. Hermes's documented fallback_model is single-shot ("at most once per session"), so this is at best a partial mitigation, but empty is worse than configured-to-a-known-good.

## 5. Coordinator Hermes HTTP Client Bugs (affects Boot/Kelk only)

These do NOT explain IG-88's overnight failure, but they are real defects that will bite Boot/Kelk the first time Chris tries heavy tool use there. Tracking here so they're not forgotten.

### Bug-C1 — Profile name passed as model ID

**Location:** `coordinator/src/agent.rs:394-397`
```rust
match run_hermes_http_query(
    &agent_name, client, profile,  // ← profile ("boot", "kelk") passed as model
    &user_msg.content, system_prompt.as_deref(),
).await {
```

Then `hermes_adapter.rs:117-120`:
```rust
let body = serde_json::json!({
    "model": model,      // ← "boot" or "kelk"
    "messages": messages,
});
```

Hermes-serve.py forwards `model` straight to the backend. mlx-vlm may silently accept any model string (since it only has one model loaded anyway) — but the effect is that the coordinator's claimed model ID is nonsense. If Hermes's runtime_provider ever tightens validation, this will 400 immediately.

**Fix:** Read the actual model from the Hermes profile config (or accept a model override from agent-config.yaml). Pass the correct string.

### Bug-C2 — `tool_calls` field dropped from response parsing

**Location:** `coordinator/src/hermes_adapter.rs:140-143`
```rust
let content = parsed["choices"][0]["message"]["content"]
    .as_str()
    .unwrap_or("")
    .to_string();
```

Only `content` is extracted. `tool_calls` array is silently discarded.

**Consequence:** If Boot or Kelk emit structured tool calls via OpenAI-format, the coordinator sees an empty `content` and returns nothing useful. Any future Boot/Kelk tool use via coordinator dispatch will be invisible to the approval system.

**Fix:** Extend `chat()` return type to carry tool_calls, wire to coordinator's tool approval path.

### Bug-C3 — No HTTP→subprocess retry diagnostics

**Location:** `coordinator/src/agent.rs:402-406`

HTTP failure falls through silently to subprocess fallback with a single `warn!`. No HTTP body is logged, so diagnosing HTTP 400s from the coordinator log requires correlating timestamps against `hermes-{boot,kelk}.log` by hand.

**Fix:** Log HTTP response body on failure before falling through.

## 6. Port and Plist Hygiene (latent risks)

From the port-contention audit:

| Item | Status | Risk if ignored |
|---|---|---|
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-41961.plist` | Stale, unloaded, conflicts with `mlx-vlm-factory` on same port | HIGH — any "reload all" script would produce a bind error |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-41988.plist` | Stale, unloaded, conflicts with `mlx-vlm-ig88` on same port | HIGH — same hazard for IG-88's dedicated server |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-41962.plist` | Stale, refers to retired port | MEDIUM |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-41963.plist` | Stale, Nan model retired | LOW (preserve if Nan observer role is coming back) |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-41966.plist` | Stale, heavy-reasoning tier retired | LOW (same) |
| `infra/ports.csv` | Lines 20-30 describe pre-FCT054 world | MEDIUM — agents and humans both read this as canonical |
| `~/.hermes/profiles/ig88/fallback_providers: []` | Empty, no escape hatch | MEDIUM |

No active port contention. No EADDRINUSE errors in any factory log. Runtime state is clean.

## 7. Remediation Plan (proposed, pending approval)

The plan is staged by blast radius: smallest-safest-first. Items marked **[IG-88]** are required before IG-88 can run another autonomous session. Items marked **[B/K]** are Boot/Kelk-only and can land later.

### Phase 1 — Stabilize IG-88 for tonight's autonomous run (blocking)

1. **[IG-88] Verify `provider: custom` is present in `~/.hermes/profiles/ig88/config.yaml`** — already confirmed during investigation. Document in the profile a loud comment explaining why removing it is dangerous.
2. **[IG-88] Set `fallback_providers`** to a specific, known-good cloud model (e.g., `google/gemma-4-31b-it` via OpenRouter) so stuck local inference has an escape hatch. Alternatively: set `fallback_model` (Hermes's documented single-shot fallback) rather than the custom-shaped `fallback_providers` field.
3. **[IG-88] Investigate mlx_vlm tool-call parsing.** This is the critical one. Options:
   - (a) Check if `mlx_vlm.server` has an undocumented tool-call parser flag
   - (b) Check if Gemma 4 E4B's HF model card includes the tool-use chat template, and whether mlx_vlm is applying it
   - (c) Accept that Gemma 4 E4B is too small for reliable tool calls, and switch IG-88 to a larger local model (Qwen 2.5 14B at 4-bit fits in 32 GB; Hermes docs explicitly list Qwen 2.5 as a native-tool-calling model)
   - (d) Temporarily pin `tool_use_enforcement: true` in profile to force prompt-template tool calling (Hermes's fallback mechanism for non-native models) — may give 4B Gemma a better shot
4. **[IG-88] Set a Hermes inference request timeout** below the 600s agent-execution ceiling. Without a documented Hermes config key for this, the practical mitigation is to wrap the gateway in a watchdog that kills and restarts after N minutes of no progress — but a better answer is to find the Hermes source's HTTP client and pass a timeout via the profile. Research required.
5. **[IG-88] Clean up corrupted memory.** The memory file(s) IG-88 wrote last night during the path-correction loop are partially corrupted. Audit `~/dev/factory/agents/ig88/memory/ig88/` for truncated content, roll forward to a known-good state, or delete offending files.
6. **[IG-88] matrix-nio dependency check** — add a preflight to `hermes-ig88.sh` that verifies `matrix-nio` is importable before exec'ing the gateway. Fails fast with a clear message instead of KeepAlive looping.

### Phase 2 — Plist and port hygiene (no-risk cleanup)

7. Remove `~/Library/LaunchAgents/com.bootindustries.mlx-lm-41961.plist` and `.mlx-lm-41988.plist`. These are the two highest-risk stale plists.
8. Decide on the fate of `.mlx-lm-41962.plist`, `.mlx-lm-41963.plist`, `.mlx-lm-41966.plist` — delete or archive to `~/dev/factory/plists/archive/`.
9. Rewrite `infra/ports.csv` lines 20-30 to reflect the post-FCT054 reality: `:41961 mlx-vlm-factory (Boot + Kelk shared)`, `:41962 retired`, `:41963 unused`, `:41966 unused`, `:41970 hermes-boot HTTP`, `:41971 retired`, `:41972 hermes-kelk HTTP`, `:41988 mlx-vlm-ig88 (dedicated)`.

### Phase 3 — Coordinator Hermes HTTP client fixes (Boot/Kelk)

10. **[B/K] Fix Bug-C1** in `coordinator/src/agent.rs:395` — pass actual model path (from Hermes profile or agent-config) instead of profile name.
11. **[B/K] Fix Bug-C2** in `coordinator/src/hermes_adapter.rs:110-155` — extend `chat()` to return tool_calls alongside content. Wire to approval system.
12. **[B/K] Improve diagnostics** — log HTTP response body on failure before subprocess fallback.
13. Add coordinator unit tests for the dispatch path covering the profile-as-model-id regression.

### Phase 4 — Systemic hardening (workspace-wide)

14. **Structural defense against the OpenRouter-routing-with-local-path bug.** The current defense (`provider: custom` per profile) is discipline-based. A better defense is to *not* inject `OPENROUTER_API_KEY` into IG-88's env unless it's actually the active provider. Options:
    - Narrow Infisical secret scoping per agent (IG-88 only gets OPENROUTER_API_KEY when cloud fallback is configured)
    - A hermes-ig88.sh preflight that `unset OPENROUTER_API_KEY` unless the profile declares a cloud fallback
    - Upstream PR to Hermes: when `base_url` + `provider: custom` are both set in profile, error loudly on env-var override instead of silently re-routing
15. **mlx_vlm tool-calling investigation** — if mlx_vlm really has no tool-call parser translation, this is a workspace-wide blocker for any local-agent tool use. Either contribute a parser upstream, swap to a backend that has one (llama.cpp + `--jinja`, or vLLM if Apple Silicon-compatible), or accept cloud-only tool use for now.
16. **Agent handoff discipline** — per `feedback_agent_handoff_accuracy.md`, all future prompts sent to downstream agents must use absolute paths verified by me before transmission.

## 8. Open Questions for Chris

1. **Model size vs. model tier.** FCT054's consolidation to Gemma 4 E4B (IG88011 Tier 1) was driven by reasoning-token-waste with Qwen 3.5 4B, not by tool-calling reliability. Are we willing to revisit this if the conclusion is "4B is too small for IG-88's tool-heavy workload"? A larger local (Qwen 2.5 14B 4-bit) would give up some speed for a lot of tool reliability.
2. **Cloud fallback policy.** IG-88 currently has no fallback. Do you want it to cloud-failover when local inference stalls, knowing the TOS/cost implications?
3. **Priority ordering for Phase 1.** Items 3 (tool-call parsing) and 4 (inference timeout) are the highest-impact. Want me to deep-dive one first or run them in parallel?

## 9. References

- [1] Hermes Agent docs — Providers: https://hermes-agent.nousresearch.com/docs/integrations/providers
- [2] Hermes Agent docs — Configuration: https://hermes-agent.nousresearch.com/docs/user-guide/configuration
- [3] Hermes Agent docs — Architecture: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture
- [4] FCT054 — Local E4B Model Consolidation
- [5] FCT052 — Hermes Agent Latency Fix, Phase 4 HTTP Daemon
- [6] FCT046 — Provider Failover Chain and Hermes Integration Architecture
- [7] IG-88 error log: `~/.hermes/profiles/ig88/logs/errors.log`
- [8] Request dumps (non-retryable 400s): `~/.hermes/profiles/ig88/sessions/request_dump_20260408_*.json`

## 10. Phase 4 Execution Notes (2026-04-08)

Phase 4 = systemic hardening. Tasks 4a–4d executed below.

### 10.1 Task 4a — Preflight guards in hermes-{ig88,boot,kelk}.sh

**Status:** COMPLETE. All three wrapper scripts now contain a preflight block that runs before the `exec` line. Distinct exit codes for grep-able launchd diagnostics:

| Exit | Check | Failure mode prevented |
|---|---|---|
| 2  | `MATRIX_TOKEN_PAN_IG88` env var present (ig88 only) | Pre-existing token-missing guard |
| 3  | Profile config exists AND contains `^provider:[[:space:]]*custom` | RC-1: silent OpenRouter routing of local model paths |
| 4  | `import nio` succeeds in hermes-agent venv | RC-4: 00:32 KeepAlive respawn loop |
| 5  | `/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json` exists | Catches a deleted/moved model before gateway crash |
| 6  | `curl -sf --max-time 3 http://127.0.0.1:<port>/health` succeeds | Avoids 000-retry storms when mlx-vlm is down |

Health endpoint confirmed: `GET /health` returns `{"status":"healthy","loaded_model":...}` on both `:41961` and `:41988` (`mlx_vlm/server.py`).

Total preflight wall-time per script measured <1s in good-state — well under the 5s budget.

Files:
- `/Users/nesbitt/dev/factory/scripts/hermes-ig88.sh:46-99` — preflight block, then `exec` at :103
- `/Users/nesbitt/dev/factory/scripts/hermes-boot.sh:16-65` — preflight block, then `exec` at :67
- `/Users/nesbitt/dev/factory/scripts/hermes-kelk.sh:16-63` — preflight block, then `exec` at :65

**Plist deployment status:** Only `com.bootindustries.hermes-ig88.plist` already invokes its wrapper. The Boot and Kelk plists currently call `hermes-serve.py` directly (`/Users/nesbitt/Library/LaunchAgents/com.bootindustries.hermes-{boot,kelk}.plist`). The wrappers `hermes-boot.sh` and `hermes-kelk.sh` are drop-in replacements ready for adoption. **Plists not modified per Phase 4 scope** — user decides deployment timing. To adopt, replace the multi-arg `ProgramArguments` with a single invocation of the wrapper script.

### 10.2 Task 4b — Infisical scoping investigation (research only)

**Current state:** All three plists invoke `infisical-env.sh` with project name **`factory`** (not the per-agent projects that exist in the script). Whatever is stored in the `factory` Infisical project gets injected into all three Hermes processes. `OPENROUTER_API_KEY` therefore enters IG-88's environment unconditionally.

**Three Infisical projects already provisioned** in `infisical-env.sh`: `factory`, `bootindu`, `ig88`. The `ig88` project is dedicated to IG-88 but currently unused by the launchd plists.

**Feasibility:** HIGH. Per-machine scoping is unnecessary — per-project scoping is already supported by the wrapper. To remove `OPENROUTER_API_KEY` from IG-88's env without affecting Boot/Kelk:

1. Move `OPENROUTER_API_KEY` from the `factory` Infisical project to a new `factory-cloud` project (or just leave it in `factory` and stop using `factory` for IG-88).
2. Create an IG-88-specific project (`ig88` is already wired in `infisical-env.sh:48-52`) containing only the secrets IG-88 actually needs: `MATRIX_TOKEN_PAN_IG88`, machine identity creds.
3. Change the IG-88 plist's first arg from `factory` to `ig88`.
4. Boot and Kelk continue using `factory` and continue receiving `OPENROUTER_API_KEY` for cloud failover.

**Belt-and-braces option** without touching Infisical: add `unset OPENROUTER_API_KEY OPENROUTER_API_KEY_FALLBACK ANTHROPIC_API_KEY` to `hermes-ig88.sh` immediately before `exec`. This is a one-line addition that defeats RC-1 even if `provider: custom` is later removed from the profile. Defense in depth — recommended regardless of Infisical scoping decision.

**Risk:** LOW. The `ig88` project already exists in the wrapper config. The migration is a one-line plist edit + secret moves. Reversible.

### 10.3 Task 4c — mlx_vlm tool-call parser investigation (the critical input for Phase 1)

**Headline:** mlx_vlm 0.4.4 **does have** a Gemma 4 tool-call parser, **does** load it automatically based on the chat template, and **does** populate the OpenAI `tool_calls` array correctly. The Phase 1 conjecture that mlx_vlm has no tool parsing was wrong. The actual failure is more subtle and is documented in two open upstream PRs that exactly match our overnight symptoms.

**Direct evidence:**

1. **Version installed in venv:** `mlx_vlm 0.4.4` at `/Users/nesbitt/dev/vendor/mlx-vlm/.venv` (`pyproject.toml` HEAD, single commit `90732bd`).
2. **Server CLI flags:** `python -m mlx_vlm.server --help` shows zero tool-related flags. Tool parsing is implicit, not opt-in.
3. **Parser source:** `/Users/nesbitt/dev/vendor/mlx-vlm/mlx_vlm/tool_parsers/gemma4.py:1-166`. Parses `<|tool_call>call:NAME{ARGS}<tool_call|>` blocks with full nested-brace handling and Gemma's `<|"|>...<|"|>` string-escape syntax. Verified end-to-end against the exact format from our overnight session: input `call:search_files{path: <|"|>/tmp<|"|>}` yields `{"name": "search_files", "arguments": {"path": "/tmp"}}`.
4. **Auto-detection:** `mlx_vlm/tool_parsers/__init__.py:13-31` adds `("<|tool_call>", "gemma4")` to the marker table. `_infer_tool_parser` scans the loaded model's `tokenizer.chat_template` for that string. Gemma 4 E4B's chat template (`/Users/nesbitt/models/gemma-4-e4b-it-6bit/tokenizer_config.json`) does contain `<|tool_call>` (verified via direct load — chat_template length 11926 chars, marker present). So parser auto-loads correctly for our exact model.
5. **Server wiring:** `mlx_vlm/server.py:1098-1105` infers parser from chat_template, `:1170-1177` calls `process_tool_calls` in the streaming path, `:1252-1259` does the same for non-streaming. Both code paths attach the parsed `tool_calls` array to the response.

**So why did the overnight loop happen?** Two open upstream PRs against `Blaizzy/mlx-vlm` describe the exact failure surface:

#### Upstream PR #974 — "Strip tool-call markup from streamed delta.content" (OPEN)
The streaming loop forwards `chunk.text` to the client verbatim, so the raw `<|tool_call>call:NAME{...}<tool_call|>` markup lands in `delta.content` even though the **same response** also carries a structured `tool_calls` array in the final delta. From the PR body: "Strict OpenAI Chat Completions clients treat `delta.content` as user-visible assistant output, so the raw parser syntax rendered on top of the tool execution frame in the client UI." The non-streaming path is correct (`remaining_text` is stripped and used as content) but the streaming path is not. PR contains a fix with four streaming tests. Not yet merged.

#### Upstream PR #964 — "Set finish_reason to 'tool_calls' when the model emits tool calls" (OPEN)
Both `server.py:1182` (streaming `ChatStreamChoice`) and `server.py:1264` (non-streaming `ChatChoice`) hardcode `finish_reason="stop"` even when the response includes a populated `tool_calls` array. The OpenAI Chat Completions spec mandates `finish_reason="tool_calls"` in this case, and strict clients use that field as the branch condition for entering the tool-execution loop. Without the fix, spec-strict clients treat tool-emitting responses as plain stops and never execute the tools. PR contains a two-test fix. Not yet merged.

**Combined effect on Hermes** (which is a strict OpenAI client per its docs §integrations/providers): each Gemma 4 E4B response contains:
- `content` = full assistant text **including** the raw `<|tool_call>...<tool_call|>` markup verbatim (PR #974 bug)
- `tool_calls` = the correctly parsed structured array (works fine, but Hermes ignores it because...)
- `finish_reason` = `"stop"` instead of `"tool_calls"` (PR #964 bug)

Hermes's logic: see `finish_reason=stop` → response is final assistant text → record `content` as message → next turn, model sees its previous "assistant text" full of literal `<|tool_call>` markup → hallucinates that it already attempted the tool and got no result → re-emits the same call → infinite loop until 600s ceiling fires. **This is exactly the FCT055 §3 03:01 timeout.**

**Implication for Phase 1 model-size decision:** The 4B-vs-14B-vs-cloud question is now decoupled from this bug. Even Qwen 2.5 14B or any other local model would hit the same dead-loop because the bug is in the **server response framing**, not the model's tool-call quality. Switching models is not a valid mitigation. The mitigations are:

| Option | Effort | Risk | Notes |
|---|---|---|---|
| (A) Cherry-pick PR #974 + #964 patches into our local mlx_vlm checkout | Low (apply two diffs, restart `mlx-vlm-{factory,ig88}`) | Low — both PRs have tests included | **Recommended.** Diffs available at `https://github.com/Blaizzy/mlx-vlm/pull/{974,964}.patch`. Both authors appear to be the same outside contributor; likely merge-clean. |
| (B) Wait for upstream merge | Zero | Unknown timeline | Both PRs sat as "open" at investigation time. |
| (C) Force prompt-template tool calling via Hermes `tool_use_enforcement: true` | Low (one profile flag) | Medium — prompt-template tool calling is a 4B-class reliability roulette anyway | Bypasses mlx_vlm tool parsing entirely, makes Hermes parse from text. Worth A/B'ing once (A) is in. |
| (D) Switch backend to llama.cpp `--jinja` | High (new server, new plist, model re-quant) | Medium | Last resort if (A) doesn't apply cleanly. |
| (E) Switch backend to vLLM | Not applicable | — | vLLM is CUDA-only; no Apple Silicon support. |

**Other relevant open issues found via GitHub search** (`repo:Blaizzy/mlx-vlm gemma tool call`, 17 results total): #962/#963 (hyphenated function names — already merged), #914/#916 (nested arguments — already merged), #926 (Falcon Perception + Gemma4 agentic demo — open, unrelated), #819 (diagnostic report — open). The Gemma 4 parser has been actively maintained in the last two months. We are catching the upstream stack mid-stabilization.

**No model changes, no mlx_vlm package modifications, no plist edits made during this investigation.** Research only, per scope.

### 10.4 Task 4d — Documentation

This section.

### 10.5 Surprises and blockers

- **Surprise 1:** mlx_vlm tool parsing exists and works. The Phase 1 plan's option (a) — "check if mlx_vlm.server has an undocumented tool-call parser flag" — is moot. There is no flag because parsing is automatic, and it works. The bug is at the response-framing layer, two open PRs upstream.
- **Surprise 2:** Gemma 4 E4B's tokenizer chat_template natively emits the correct tool-call markers. The 4B model is not the bottleneck on tool format compliance — it's correctly producing `<|tool_call>...<tool_call|>` blocks (verified by the existence of a working parser that Gemma generated correct input for during both test cases #962 and #914). Whether 4B reliably *decides when* to call tools is a separate question that this investigation did not address.
- **Surprise 3:** All three plists share Infisical project `factory`. The `ig88` Infisical project exists in `infisical-env.sh` but is unused. RC-1's structural defense is one plist arg away.
- **Surprise 4:** The Boot and Kelk wrapper scripts already exist and pre-date Phase 4 (`hermes-boot.sh` and `hermes-kelk.sh`, mtime 2026-04-08 10:29). They had identical preflight blocks staged. No new files created during Phase 4.
- **Blocker:** None for Phase 4 itself. Phase 1 (model size / tool reliability) now blocks on the cherry-pick decision for upstream PRs #974 and #964.
