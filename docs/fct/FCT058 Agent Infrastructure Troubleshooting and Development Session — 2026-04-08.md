# FCT058 Agent Infrastructure Troubleshooting and Development Session — 2026-04-08

**Status:** Session record — durable reference, no follow-up actions blocked on this doc
**Date:** 2026-04-08
**Scope:** End-to-end debugging, architecture design, and runtime hardening across all three factory agents (Boot, IG-88, Kelk) following IG-88's overnight autonomy failure 2026-04-07 → 08
**Related:** FCT054, FCT055, FCT056, FCT057

---

## 1. Summary

This document records a single long working session on 2026-04-08 that began as a forensic post-mortem of IG-88's first autonomous overnight session and evolved into a workspace-wide hardening pass touching every layer of the agent runtime stack — Hermes profiles, wrapper scripts, mlx-vlm, the coordinator HTTP dispatch path, soul files, agent docs trees, the matrix message pipeline, and the governing vocabulary itself. Four FCT documents were created during this session (FCT055, FCT056, FCT057, and this one); a fifth (FCT054, landed the previous day) is the immediate background.

The session opened with FCT055 — a forensic walk through `~/.hermes/profiles/ig88/logs/` that identified four stacked failure modes (path typo, provider routing bug, matrix-nio dependency gap, 600s tool-call dead-loop) and traced the dead-loop root cause to two open upstream PRs against `Blaizzy/mlx-vlm` (#974 and #964). The Phase 4 execution notes appended to FCT055 recorded preflight-guard wrapper scripts, an Infisical scoping investigation, and the mlx-vlm tool-call parser deep dive. Midday the work pivoted to architecture: Chris's critique of the tier/cascade framing produced FCT056 (ensemble agents and face-based cognition) along with `scripts/face-consultant-mcp.py` and a passing smoke test. Afternoon work was a long sequence of small infrastructure bugs surfaced as IG-88 and Kelk tried to do real work on the freshly hardened stack: max_tokens truncation at 256, TERMINAL_CWD inheritance, auxiliary-routing fallthrough to OpenRouter, the PREFIX collision protocol, the SOUL.md vs CLAUDE.md confusion, Kelk's timeline directory split-brain, and an interrupted IG88015 write caused by a mid-task gateway restart.

The deliverables that landed this session: FCT055 (post-mortem + Phase 4 execution notes), FCT056 (ensemble vocabulary + face-consultant MCP server + tests), FCT057 (matrix message chunking design — design only, no implementation), three rewritten Hermes SOUL.md files (66/77/87 lines, previously 11–20), three rewritten wrapper scripts with preflight guards and TERMINAL_CWD export, three Hermes profiles with `provider: custom`, `max_tokens: 32768`, and explicit `auxiliary.*` blocks, three coordinator bug fixes (Bug-C1/C2/C3) with eleven new unit tests, two safety stashes, a cleaned-up `.gitignore`, hardened Kelk private foundation directory, and this doc.

What's still in flight as of writing: **IG88015 recovery is pending** — IG-88's session was interrupted by a mid-task gateway restart at 13:00:27 and the orientation report write never landed; a follow-up clarification prompt has been queued (see §8). The FCT057 chunking implementation is deferred per Chris's direction. The face-consultant MCP server is built and tested but not yet wired into IG-88's profile pending verification of `OPENROUTER_API_KEY` env passthrough to the MCP child process.

---

## 2. Session Timeline

All times local on 2026-04-08 unless otherwise noted. Previous-night events from `~/.hermes/profiles/ig88/logs/errors.log`.

### Morning — post-mortem and Phase 1–4 remediation

- **2026-04-07 evening (origin event):** Chris assigns IG-88 its first autonomous self-development session (backtest + paper-trade infrastructure validation) via Matrix DM. The handoff prompt uses `~/factory/agents/ig88/...` instead of `/Users/nesbitt/dev/factory/agents/ig88/...`.
- **00:32:28, 00:32:43, 00:32:59 (overnight):** `hermes-ig88` launchd-bounces three times with `gateway.platforms.matrix: matrix-nio not installed`. KeepAlive respawns the gateway into the same failure across 30 seconds until the dep is present (RC-4).
- **01:32:25:** First HTTP 400 from `/Users/nesbitt/models/gemma-4-e4b-it-6bit is not a valid model ID` — the provider routing bug (RC-1). `provider: custom` was not yet pinned in the IG-88 profile; Hermes silently routed local-path requests to OpenRouter.
- **01:34:52:** Same HTTP 400 second occurrence. `provider: custom` then added to `~/.hermes/profiles/ig88/config.yaml:8` mid-session. No further 400s on that path.
- **03:01:06:** `Agent execution timed out after 600s for session agent:main:matrix:dm:!...:matrix.org`. Local inference was working, but Gemma 4 E4B's tool calls were leaking as raw `<|tool_call>` text into `delta.content`, the model re-emitted them in an infinite "I just tried" loop, and the 600s ceiling fired. This is the dominant overnight death (RC-2).
- **~08:00–10:00 (morning):** FCT055 forensic timeline assembled from `~/.hermes/profiles/ig88/logs/errors.log`, `~/.hermes/profiles/ig88/sessions/request_dump_*.json`, `~/Library/Logs/factory/hermes-ig88.log`, `mlx-vlm-ig88.log`. Six root causes ranked. Phase 1–4 remediation plan drafted.
- **~10:30:** Phase 4 wrapper scripts staged. `scripts/hermes-{ig88,boot,kelk}.sh` get preflight guards with exit codes 2–6.
- **~10:48:** mlx-vlm streaming-off workaround applied to IG-88's profile (`display.streaming: false`). Direct probe to `:41988` confirms clean structured `tool_calls` on the non-streaming path. Workaround for upstream PRs #974/#964.
- **~11:00:** mlx-vlm tool-call parser deep-dive (FCT055 §10.3) completes — proves the parser exists and works, identifies the upstream PRs, recommends cherry-pick option (A) deferred. Phase 4 documented.
- **~11:30–11:45:** Handoff prompts for IG-88 and Kelk drafted in `260408-handoff-prompts.md`. All paths verified on disk before commit.

### Midday — ensemble vocabulary and face-consultant MCP

- **~11:45:** Chris's critique lands: "tier/fallback distorts how we *reach* for the 31B." The vocabulary discussion produces ensemble agent / face / current / tide / turn / eddy pool / conductor / wash. The flow vocabulary is concentrated in §1–§3.5 of FCT056; engineering language takes over from §4. The pinball/ricochet aside in §3.5 acknowledges that within-agent cognition is continuous flow while workspace infrastructure is discrete ricochet, and the two views are compatible at different scales.
- **~12:00:** Hermes internals research in parallel: aux slots are a fixed schema with 8 hardcoded keys, `mixture_of_agents_tool.py:63` hardcodes 4 OpenRouter models, LiteLLM is complementary infra not a substitute. Decision: MCP-server-as-consultant (option A in FCT056 §4).
- **~12:00 (concurrent with above):** Original Kelk handoff fails as Kelk attempts to read `kelk-transcript_wip.json` (5272 lines, ~438KB) end-to-end. mlx-vlm-factory on `:41961` is hammered with repeated ~48k-token prefill attempts. Coordinator's 120s HTTP timeout fires repeatedly. Kelk's hermes-serve daemon is restarted at ~12:05 (new PID 51403) to break the loop. Reduced corpus correction (~50KB, 4 files) is sent.
- **~12:10:** After IG-88's first orientation report comes back suspiciously short, the truncation at ~250 tokens / ~1KB is traced to mlx-vlm's `DEFAULT_MAX_TOKENS = 256` defaulting through `hermes-serve.py` (which was not forwarding `max_tokens` from profile config). Fix lands: `hermes-serve.py:62,78` reads `max_tokens` from profile top-level or `agent.max_tokens`, passes to `AIAgent`. All three profiles get `max_tokens: 32768`. End-to-end probe to Boot returns `count 1-100` complete with `finish_reason=stop`. IG-88 daemon restarted (PID 61915).
- **~12:30:** FCT056 proposal lands with Phase 1 vocabulary, Phase 2 face-consultant MCP wiring sketch, Phase 3 smoke test plan, and Phase 4 extension to Boot/Kelk.
- **~12:46:** First safety stash created — `.stash/ig88-recovery-20260408/` with three byte-identical copies of IG88013 (disk, HEAD, commit `b9462bb`). At this point Chris feared IG-88 may have damaged the file; later verification proved the on-disk copy was intact.
- **~12:49:** Second safety stash — `.stash/docs-snapshot-20260408-124942/` (1.0 MB, 40 files, all three agent docs trees). `.gitignore` rule added for `.stash/`.

### Afternoon — runtime bugs, soul rewrites, and the IG88015 interruption

- **~12:55:** `scripts/face-consultant-mcp.py` (694 lines) and `test-face-consultant-mcp.py` smoke test (54 assertions passing) committed alongside FCT056.
- **~13:00:** IG-88 picks up the recovery prompt and begins composing IG88015 (sprint orientation report + IG88013 recovery acknowledgment).
- **13:00:27:** Auxiliary-routing fix lands (RC explained in §3.11). All three Hermes profiles now have explicit `auxiliary.*` blocks pinning each subsystem to local mlx-vlm. Daemon restart issued for IG-88 to pick up the new config — **mid-turn**. IG-88's session is killed silently. The IG88015 write never happens.
- **~13:02–13:05:** "Where is IG88015?" investigation begins. No file on disk. No write attempt in `hermes-ig88.log`. Daemon was restarted at 13:00:27. Cause established: not a file-write failure, an interrupted session.
- **~13:03:** `feedback_no_mid_task_restarts.md` saved to project memory.
- **~13:10–13:30:** Kelk timeline split-brain discovered — Kelk had written `personal_history_tracker.md` to a recreated `docs/timeline/` directory (which had been deleted during foundation reorganization earlier in the day). Reconciled by moving the tracker into `docs/klk/foundation/timeline/` alongside the decade files, removing `docs/timeline/` entirely, updating Kelk's `agents/kelk/CLAUDE.md` and `~/.hermes/profiles/kelk/SOUL.md` to make the correct path explicit and explicitly warn against the old path.
- **~13:30–14:30:** PREFIX collision protocol surfaced as a separate concern. IG-88 had attempted to overwrite IG88013 (or treated the recovery as a write of an existing number) because the soul-file guidance was framed as "here's how you'd find the next number" rather than "you MUST run this lookup before writing." All three SOUL.md files rewritten: Boot 11 → 77 lines, IG-88 17 → 87 lines, Kelk 20 → 66 lines. Each gets a "Creating New Documents — MANDATORY Protocol" section with absolute paths, explicit collision check, and the rule that handoff prompts naming specific numbers are informational, not authoritative.
- **~14:30–15:00:** TERMINAL_CWD inheritance bug found while testing the rewritten soul files. Hermes's file toolset reads `TERMINAL_CWD` from environment, not from any profile `terminal.cwd:` field. Boot and Kelk wrappers were not setting it. Fixed via `export TERMINAL_CWD=/Users/nesbitt/dev/factory/agents/<name>` + `cd "$TERMINAL_CWD"` in all three wrapper scripts, plus plist updates to invoke the wrappers (rather than calling `hermes-serve.py` directly).
- **~15:00–15:30:** SOUL.md vs CLAUDE.md confusion clarified. Hermes runtime reads `~/.hermes/profiles/<name>/SOUL.md`; `agents/<name>/CLAUDE.md` is the Claude Code context file, not the agent runtime file. Both files now share most of their content but they serve different readers; a unification strategy is deferred.
- **~15:30:** Kelk private foundation hardening — `docs/klk/foundation/`, `docs/klk/archive/`, `docs/timeline/` added to `.gitignore` (lines 55–63). Files untracked via `git rm --cached`. Local permissions chmod 600/700. Repo confirmed private on GitHub. History purge deferred.
- **~16:00:** This document drafted.

---

## 3. Bugs Found, Root Causes, and Fixes

Bugs are listed in **discovery order** so the reasoning chain is followable. Each entry: symptom / root cause / fix / verification / files.

### 3.1 RC-1 — Hermes provider routing bug (overnight)

**Symptom:** HTTP 400 `is not a valid model ID` returned from OpenRouter. Local inference never reached.

**Root cause:** `runtime_provider.py:340–389` (`/Users/nesbitt/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/hermes_cli/runtime_provider.py`) honors profile `base_url` only when `(requested_norm == "auto" AND cfg_provider in {"", "auto"})` OR `(requested_norm == "custom" AND cfg_provider == "custom")`. When `OPENROUTER_API_KEY` is in env (injected by Infisical via `hermes-ig88.sh:42-43`), `requested_norm` auto-resolves to `"openrouter"`, neither branch matches, the `base_url` is silently dropped, and the local filesystem path gets forwarded to `https://openrouter.ai/api/v1/chat/completions` as the `model` field.

**Fix applied:** Mid-session — `provider: custom` added to `~/.hermes/profiles/ig88/config.yaml:8`. Later hardened with explicit `provider` forwarding in `hermes-serve.py:69-72` so that the AIAgent constructor receives the profile provider rather than defaulting to `""` (which would otherwise leave the runtime resolver in the same broken state).

**Verification:** No further HTTP 400s after 01:34:52 in `~/.hermes/profiles/ig88/logs/errors.log`. End-to-end probe to all three daemons returns `200 OK` with local inference responses.

**Files:** `~/.hermes/profiles/{ig88,boot,kelk}/config.yaml` line 3/7/8; `scripts/hermes-serve.py:62-83`; `scripts/hermes-{ig88,boot,kelk}.sh` (preflight guard, exit code 3).

### 3.2 RC-2 — mlx-vlm streaming response framing (the 600s dead-loop)

**Symptom:** Each response from Gemma 4 E4B contained the raw `<|tool_call>...<tool_call|>` markup verbatim in `delta.content` *and* a correctly populated structured `tool_calls` array. Hermes (a strict OpenAI client) saw `finish_reason="stop"` instead of `"tool_calls"` and treated the raw markup as final assistant text. On the next turn, the model saw its previous "assistant text" full of literal tool-call markup, hallucinated that it had already attempted the tool, re-emitted the same call, and looped until the 600s ceiling fired at 03:01.

**Root cause:** Two open upstream PRs against `Blaizzy/mlx-vlm`:
- **PR #974** — `server.py` streaming path forwards `chunk.text` to `delta.content` verbatim instead of stripping the parser markup. Non-streaming path is correct.
- **PR #964** — both `server.py:1182` (streaming `ChatStreamChoice`) and `server.py:1264` (non-streaming `ChatChoice`) hardcode `finish_reason="stop"` even when `tool_calls` is populated. Spec mandates `"tool_calls"`.

**Fix applied:** Streaming-off workaround. `display.streaming: false` set in IG-88's profile. The non-streaming path strips the parser markup correctly and the bare `finish_reason="stop"` is tolerated by Hermes when only structured `tool_calls` come back. Cherry-pick of the upstream patches deferred.

**Verification:** Direct curl probe to `:41988` post-fix returned a clean response with parsed `tool_calls` and no `<|tool_call>` text leakage. Documented in FCT055 §10.3.

**Files:** Investigation evidence in `/Users/nesbitt/dev/vendor/mlx-vlm/mlx_vlm/tool_parsers/gemma4.py:1-166`, `/Users/nesbitt/dev/vendor/mlx-vlm/mlx_vlm/server.py:1098-1259`. PRs at `https://github.com/Blaizzy/mlx-vlm/pull/{974,964}`.

### 3.3 matrix-nio dependency missing at gateway restart

**Symptom:** Three launchd respawns of `hermes-ig88` between 00:32:28 and 00:32:59 with `gateway.platforms.matrix: matrix-nio not installed; Gateway failed to connect any configured messaging platform`.

**Root cause:** FCT054 cutover restarted the gateway before verifying the `hermes-agent` venv had `matrix-nio` installed. Transient (resolved within 30s when the dep was present) but visible because launchd KeepAlive looped through three failures.

**Fix applied:** Preflight guard in `scripts/hermes-ig88.sh` runs `python3 -c 'import nio'` against the hermes-agent venv before exec'ing the gateway. Exit code 4 on failure (grep-able in launchd diagnostics). Guard wall-time <1s in good state. Same pattern added to Boot and Kelk wrappers (where matrix-nio is not strictly required for the HTTP daemon path, but the import check is cheap).

**Files:** `scripts/hermes-ig88.sh:46-99`, `scripts/hermes-boot.sh:16-65`, `scripts/hermes-kelk.sh:16-63`.

### 3.4 Tool-call dead loop at 600s ceiling

**Symptom:** `Agent execution timed out after 600s` at 03:01:06.

**Root cause:** Direct downstream consequence of 3.2. With the streaming framing bug, the model could not escape the tool-call retry loop until Hermes's hardcoded 600s ceiling killed the session.

**Fix applied:** Resolved indirectly by the streaming-off workaround in 3.2. A faster-fail HTTP-level timeout below the 600s ceiling is not exposed by Hermes config; deferred.

**Files:** Same as 3.2.

### 3.5 Path typo propagation (`~/factory` vs `/Users/nesbitt/dev/factory`)

**Symptom:** Every file read IG-88 attempted overnight failed with "directory does not exist." IG-88 (Gemma 4 E4B, 4B local model) could not disambiguate "file does not exist" from "tool call malformed" and corrupted its working memory with garbled path-correction tool calls (`memory: "~memory: \"The primary project\""` truncated mid-edit).

**Root cause:** Chris's original handoff prompt used `~/factory/agents/ig88/...`. The correct workspace root on Whitebox is `/Users/nesbitt/dev/factory/`. The missing `dev/` was the key.

**Fix applied:** Path corrected in mid-session reprompt. All three agents' soul files (`~/.hermes/profiles/{ig88,boot,kelk}/SOUL.md`) and `agents/<name>/CLAUDE.md` files now use absolute `/Users/nesbitt/dev/factory/...` paths throughout. Two durable feedback memories captured: `feedback_agent_handoff_paths.md` and `feedback_agent_handoff_accuracy.md`. Discipline rule: every path in every handoff prompt is now verified against disk before transmission.

**Files:** `~/.claude/projects/-Users-nesbitt-dev-factory/memory/feedback_agent_handoff_{paths,accuracy}.md`. Soul/CLAUDE files commit `715efca`.

### 3.6 Coordinator Hermes HTTP client bugs (Bug-C1, C2, C3) — affects Boot/Kelk

These bugs do not explain IG-88's overnight failure (IG-88 uses the standalone gateway path, not coordinator HTTP dispatch — see `ig88_standalone_gateway.md`). They affect Boot and Kelk only.

**Bug-C1 — Profile name passed as model ID.** `coordinator/src/agent.rs:394-397` passed the profile string ("boot", "kelk") into `HermesHttpClient::new(port, profile)` which then forwarded it as the OpenAI `model` field. mlx-vlm tolerates any string (it has one model loaded), but as soon as a stricter validator gets in the path it 400s.

**Fix:** `coordinator/src/hermes_adapter.rs:130-156` now defines `parse_profile_model()` and `resolve_profile_model()` which read `~/.hermes/profiles/<profile>/config.yaml` and extract the actual `model` field. `HermesHttpClient::new()` at `:178-200` resolves the model once at construction with a degraded fallback (warn + use profile name) if resolution fails. `agent.rs:359-364` calls `client.model()` and logs the resolved value.

**Bug-C2 — `tool_calls` array dropped from response.** `hermes_adapter.rs:140-143` (pre-fix) extracted only `content`, silently discarding the `tool_calls` array.

**Fix:** `hermes_adapter.rs:73-122` adds `parse_tool_calls()` and `HermesToolCall` struct. The `chat()` return type is extended to carry tool calls alongside content. Wired into the coordinator approval system.

**Bug-C3 — No HTTP→subprocess retry diagnostics.** Pre-fix, HTTP failure fell through silently to subprocess fallback with a single `warn!`. No body logged.

**Fix:** HTTP response body now logged on failure before fallthrough.

**Tests:** 11 new unit tests in `coordinator/src/hermes_adapter.rs` (parse_profile_model on missing/empty/malformed YAML, parse_tool_calls on empty/malformed/multi-call cases, etc.).

**Files:** `coordinator/src/agent.rs:251-364`, `coordinator/src/hermes_adapter.rs:73-200`. Unit tests at the bottom of the same file.

### 3.7 Stale plists and ports.csv drift

**Symptom:** Five `~/Library/LaunchAgents/com.bootindustries.mlx-lm-*.plist` files referencing retired models and ports. `infra/ports.csv` lines 20-30 describing pre-FCT054 world.

**Root cause:** FCT054 added new mlx-vlm plists but did not delete the old mlx-lm ones. The CSV documentation lagged the runtime state.

**Fix:** Six stale plists deleted (the five mlx-lm-* files plus one orphaned hermes plist). `infra/ports.csv` lines 20-30 rewritten to reflect post-FCT054 reality (`:41961 mlx-vlm-factory`, `:41988 mlx-vlm-ig88`, `:41970 hermes-boot HTTP`, `:41972 hermes-kelk HTTP`, `:41962/63/66 retired`).

**Files:** `infra/ports.csv`, `~/Library/LaunchAgents/com.bootindustries.mlx-lm-{41961,41962,41963,41966,41988}.plist` (deleted).

### 3.8 Phase 4 preflight guards in wrapper scripts

**Symptom:** Phase 4 systemic hardening — defense in depth against the bugs above.

**Fix:** All three wrapper scripts now contain a preflight block before `exec`. Distinct exit codes:

| Exit | Check | Failure mode prevented |
|---|---|---|
| 2 | `MATRIX_TOKEN_PAN_IG88` env present (ig88 only) | Token-missing |
| 3 | Profile config exists AND contains `^provider:[[:space:]]*custom` | RC-1 |
| 4 | `import nio` succeeds in hermes-agent venv | RC-4 |
| 5 | `/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json` exists | Deleted/moved model |
| 6 | `curl -sf --max-time 3 http://127.0.0.1:<port>/health` succeeds | mlx-vlm down |

Total preflight wall-time per script <1s in good-state.

**Files:** `scripts/hermes-ig88.sh:46-99`, `scripts/hermes-boot.sh:16-65`, `scripts/hermes-kelk.sh:16-63`.

### 3.9 mlx-vlm `max_tokens=256` default (truncation)

**Symptom:** IG-88's first orientation report after the recovery prompt was suspiciously short (~250 tokens, ~1KB, ~one and a half paragraphs). Earlier responses today had been similarly clipped without anyone noticing because nothing demanded a long response.

**Root cause:** mlx-vlm's `DEFAULT_MAX_TOKENS = 256` (`mlx_vlm/generate.py:34`) fires whenever the request omits `max_tokens`. `hermes-serve.py` was constructing `AIAgent(...)` without forwarding any `max_tokens` value from the profile config, so the request reached mlx-vlm with no ceiling and got the default. The `hermes-agent` library's behavior under `max_tokens=None` is to omit the field entirely from the upstream HTTP request body.

**Fix:** `hermes-serve.py:62` now reads `max_tokens` from profile top-level or `agent.max_tokens` override and passes it to `AIAgent(max_tokens=...)` at `:78`. Logged at `:83`. All three profiles now set `max_tokens: 32768` at the top level with a "no artificial ceiling" comment (`~/.hermes/profiles/ig88/config.yaml:16`, `boot:6`, `kelk:10`).

**Verification:** End-to-end probe to Boot's daemon asking it to count 1-100. Pre-fix this would have truncated at ~70 with `finish_reason=length`. Post-fix it returned all 100 numbers with `finish_reason=stop`. The fix is confirmed working.

**Files:** `scripts/hermes-serve.py:62,78,83`; `~/.hermes/profiles/{ig88,boot,kelk}/config.yaml`; profile backups at `~/.hermes/profiles/{ig88,boot,kelk}/config.yaml.bak-20260408-maxtokens`.

### 3.10 TERMINAL_CWD not inherited by file toolset

**Symptom:** Boot and Kelk were running tool calls (file reads, file writes, ls) against the wrong working directory. Their `terminal.cwd:` profile field was being ignored.

**Root cause:** Hermes's file/terminal toolset (`tools/terminal_tool.py:492`) reads the `TERMINAL_CWD` environment variable, **not** any profile `terminal.cwd:` field. The plists were invoking `hermes-serve.py` directly without setting that env var, so the toolset defaulted to the launchd process cwd (the user's home).

**Fix:** Each wrapper script now exports `TERMINAL_CWD` explicitly to the agent's correct directory and `cd`s into it before exec:
- `scripts/hermes-ig88.sh:106-107`: `export TERMINAL_CWD=/Users/nesbitt/dev/factory/agents/ig88; cd "$TERMINAL_CWD"`
- `scripts/hermes-boot.sh:71-72`: same pattern, `agents/boot`
- `scripts/hermes-kelk.sh:69-70`: same pattern, `agents/kelk`

Plists updated to invoke the wrappers (rather than calling `hermes-serve.py` directly) so the export takes effect.

**Files:** Three wrapper scripts as cited above; plists at `~/Library/LaunchAgents/com.bootindustries.hermes-{ig88,boot,kelk}.plist`.

### 3.11 Auxiliary routing silently routing to OpenRouter

**Symptom:** Kelk hit persistent HTTP 400 errors even after the main provider forwarding fix at 3.1. Log entries showed the failures came from auxiliary subsystems (compression, session search, title generation).

**Root cause:** Hermes's `auxiliary:` config block at the profile top level controls routing for eight named auxiliary slots (`vision`, `web_extract`, `compression`, `session_search`, `skills_hub`, `approval`, `mcp`, `flush_memories`). Each slot has its own `provider` field. If unset, each slot defaults to `provider: auto`, and the auto resolver — same logic as the main provider gate at RC-1 — falls through to OpenRouter when `OPENROUTER_API_KEY` is present in env. The local-model filesystem path then gets forwarded as the model ID. HTTP 400.

The main provider being correctly pinned to `provider: custom` was not enough. Each auxiliary slot needed its own pin.

**Fix:** All three profiles now have explicit `auxiliary.*` blocks with `provider: custom` pinned per slot:
- `~/.hermes/profiles/ig88/config.yaml:52-87` (compression, session_search, skills_hub, approval, mcp, flush_memories, vision, web_extract; plus `summary_provider: custom` for compression)
- `~/.hermes/profiles/boot/config.yaml:26-65` (same shape)
- `~/.hermes/profiles/kelk/config.yaml:31-72` (same shape)

**Verification:** Kelk's HTTP 400 errors stopped after the auxiliary fix landed. This is the bug whose fix-deployment restart killed IG-88's IG88015 session at 13:00:27 (see 3.15).

**Files:** Three profile config.yaml files as cited.

### 3.12 PREFIX lookup not treated as mandatory protocol

**Symptom:** IG-88 attempted to overwrite (or treated the recovery as a write of) IG88013, the existing sprint report. Chris's recovery prompt asked for IG88015; IG-88 reached for IG88013 instead.

**Root cause:** The PREFIX-lookup guidance in the soul files was framed as "here's how you would find the next number" — informational, not procedural. With small models, informational framing is not load-bearing; the model treated the handoff prompt's mention of a specific number as authoritative and skipped the lookup. Worse, when the user-mentioned number happened to coincide with an existing file, the model had no protocol forcing it to verify.

**Fix:** The "Creating New Documents" section in all three soul files rewritten as **MANDATORY Protocol** (literal heading). Three steps now explicit:
1. Run the lookup command (exact bash invocation provided, with absolute path)
2. Verify no collision against the result
3. Write with absolute path using the resolved number

The new protocol explicitly states that handoff prompts naming a specific number are *informational, not authoritative*; the lookup result is authoritative.

**Files:** `~/.hermes/profiles/ig88/SOUL.md:35-56`, `~/.hermes/profiles/boot/SOUL.md:27-46`, `~/.hermes/profiles/kelk/SOUL.md` (analogous section). `agents/{ig88,boot,kelk}/CLAUDE.md` updated in parallel.

### 3.13 Hermes SOUL.md vs Claude Code CLAUDE.md confusion

**Symptom:** Earlier in the session I had been editing `agents/<name>/CLAUDE.md` for runtime agent guidance, expecting Hermes to read those files. Hermes does not. Hermes reads `~/.hermes/profiles/<name>/SOUL.md`. The two files serve different readers.

**Root cause:** Naming similarity and the workspace convention of putting agent-specific instructions in CLAUDE.md files. The Hermes profile SOUL.md files were minimal stubs (Boot 11, IG-88 17, Kelk 20 lines) carrying almost none of the guidance present in the CLAUDE.md files.

**Fix:** All three SOUL.md files rewritten:
- Boot: 11 → 77 lines (`~/.hermes/profiles/boot/SOUL.md`)
- IG-88: 17 → 87 lines (`~/.hermes/profiles/ig88/SOUL.md`)
- Kelk: 20 → 66 lines (`~/.hermes/profiles/kelk/SOUL.md`)

Each new SOUL.md contains: workspace path (`/Users/nesbitt/dev/factory/agents/<name>/`), project layout tree, MANDATORY PREFIX protocol with absolute path lookup command, write-path rules, domain voice. Kelk's SOUL.md additionally warns explicitly against the `docs/timeline/` vs `docs/klk/foundation/timeline/` split-brain (see 3.14).

A unification strategy (build script, symlinks, single-source-of-truth) is deferred — the two files serve different readers and the right answer is not yet obvious.

**Files:** Three SOUL.md files as above; three `agents/<name>/CLAUDE.md` files updated in parallel.

### 3.14 Kelk timeline directory split-brain

**Symptom:** Kelk had written `personal_history_tracker.md` to `docs/timeline/` after that directory had been deleted earlier in the day (during foundation reorganization that moved decade files into `docs/klk/foundation/timeline/`). The result: two directories purporting to hold timeline material, one orphaned, one canonical, with the agent confused about which to read and write.

**Root cause:** During the foundation reorganization at the start of the day, `docs/timeline/archive/` was deleted and the decade files were moved into `docs/klk/foundation/timeline/`. Kelk's CLAUDE.md and SOUL.md were updated to point at the new location, but Kelk's session was still warm with the old path in working memory. When Kelk wrote the personal history tracker, it used the old path, recreating `docs/timeline/`.

**Fix:** `personal_history_tracker.md` moved into `docs/klk/foundation/timeline/personal_history_tracker.md` alongside the decade files. The stray `docs/timeline/` directory removed entirely. Kelk's CLAUDE.md and SOUL.md updated to make the correct path explicit and add an explicit warning against the old path. `.gitignore` rule `agents/kelk/docs/timeline/` added (line 59) so any future recreation will at least not be tracked.

**Verification:** `ls /Users/nesbitt/dev/factory/agents/kelk/docs/klk/foundation/timeline/` shows seven files (six decade files + meta-map.md + personal_history_tracker.md). `ls /Users/nesbitt/dev/factory/agents/kelk/docs/timeline/` returns no such directory.

**Files:** `agents/kelk/docs/klk/foundation/timeline/personal_history_tracker.md`; `agents/kelk/CLAUDE.md`; `~/.hermes/profiles/kelk/SOUL.md`; `.gitignore:55-59`.

### 3.15 IG88015 mid-task restart (interrupted session)

**Symptom:** IG-88 was given a recovery prompt asking it to write IG88015 (orientation report). Chris observed "the write is failing" — but no IG88015 file appeared on disk and `hermes-ig88.log` showed no write attempt at all.

**Root cause:** Not a file-write failure. IG-88's session was killed at 13:00:27 by a `launchctl kickstart -k` restart of the `hermes-ig88` daemon, issued by me to pick up the auxiliary routing fix from 3.11. The restart happened mid-thought. IG-88 was preparing the IG88015 content but had not yet emitted the write tool call when the daemon got bounced. The matrix-nio session went away, the in-flight reasoning was lost, no file was ever written, no error was reported.

**Fix:** No code fix. Lesson captured as durable feedback: `feedback_no_mid_task_restarts.md`. Procedure: before any `launchctl kickstart -k` of a Hermes daemon, check `tail -20 /Users/nesbitt/Library/Logs/factory/hermes-<agent>.log` for activity in the last 60 seconds; check `~/.hermes/profiles/<agent>/logs/errors.log` for ReadTimeout/reconnect events; if active, either wait or warn the user before restarting. IG-88's gateway is especially fragile to this because it runs a matrix-nio event loop with persistent session state — a restart loses more than a subprocess daemon would.

**IG88015 recovery:** A clarifying follow-up prompt has been queued in `260408-handoff-prompts.md` (lines 197–230) telling IG-88 that (a) IG88013 is intact and needs no recovery, (b) infrastructure is now fully fixed, (c) run the MANDATORY PREFIX lookup, (d) write the orientation report at the resolved number, (e) verify the write by reading back, (f) report path/size/summary in Matrix. **As of this writing, IG-88 has not yet completed this recovery.** Update this section when the write lands.

**Files:** `~/.claude/projects/-Users-nesbitt-dev-factory/memory/feedback_no_mid_task_restarts.md`; `260408-handoff-prompts.md:197-230`.

### 3.16 Coordinator HTTP timeout vs. large prefills

**Symptom:** Coordinator's 120s HTTP timeout fired repeatedly during Kelk's first-attempt ~48k-token prefill loop. Each prefill took ~80s at ~660 tok/s on the warm mlx-vlm; with some headroom for the rest of the request, the total wall time was right at the timeout edge. Hermes daemon was restarted (PID 51403) to break the loop.

**Root cause:** 4B local models doing >30k token prefills can legitimately take >90s. The 120s ceiling is borderline.

**Fix:** Not implemented. Tracked as a follow-up (raise to 300s).

**Files:** Coordinator HTTP client constructor (location TBD when the fix lands).

### 3.17 Subprocess fallback path latent provider-routing bug

**Symptom:** During Kelk's failure loop, the coordinator's HTTP-to-subprocess fallback path at `coordinator/src/agent.rs:409-422` was triggered. The subprocess fallback does not pin `provider: custom`, so when HTTP fails it falls to subprocess which then routes to OpenRouter and sends the local model path as a model ID — same failure mode IG-88 hit overnight.

**Root cause:** Latent. The subprocess fallback was never updated to honor the `provider: custom` pin.

**Fix:** Not implemented. Preferred fix is to remove the subprocess fallback entirely, since the HTTP daemon path is the canonical path post-FCT052/FCT054 and the subprocess fallback is dead code with known bugs. Tracked as a follow-up.

**Files:** `coordinator/src/agent.rs:409-422`.

---

## 4. Safety Stashes and Backups

Two safety stashes were created during the session:

### 4.1 `.stash/ig88-recovery-20260408/` — IG88013 byte-identical copies

Created at ~12:46 when Chris feared IG-88 may have damaged IG88013 during its overnight loop. Three copies, all byte-identical:

- `IG88013 Sprint Report Backtesting and Paper Trading Build.md` — copy of disk state at the time of the stash
- `IG88013 Sprint Report Backtesting and Paper Trading Build.from-git-HEAD.md` — extracted via `git show HEAD:...`
- `IG88013 Sprint Report Backtesting and Paper Trading Build.from-commit-b9462bb.md` — extracted via `git show b9462bb:...`

Verification later confirmed all three copies were byte-identical to each other and to the live on-disk file. **No recovery was needed** — the file had never been damaged. The stash remains as a defensive artifact; can be deleted at Chris's discretion.

### 4.2 `.stash/docs-snapshot-20260408-124942/` — full agent docs tree snapshot

Created at 12:49:42 as a defense against further inadvertent damage during the session. Contains complete copies of all three agents' docs trees:

```
.stash/docs-snapshot-20260408-124942/
├── boot/
├── ig88/
└── kelk/
```

Total size: 1.0 MB, 40 files. Created via `cp -R agents/{boot,ig88,kelk}/docs/`.

### 4.3 `.gitignore` rules added

`.gitignore` updated with the following additions (lines 55–63):

- `.stash/` — all stashes ignored
- `agents/kelk/docs/klk/foundation/` — Kelk identity foundation (personal history, trauma content, family names, transcripts)
- `agents/kelk/docs/klk/archive/` — Kelk archive material
- `agents/kelk/docs/timeline/` — defensive ignore against split-brain recurrence (3.14)

### 4.4 Kelk private foundation hardening

After the foundation reorganization, the Kelk identity material was untracked from git via `git rm --cached`, the directory permissions tightened to `chmod 700` (directory) and `chmod 600` (files), and the GitHub repo was confirmed to be private. History purge (`git filter-repo` to remove the previously-committed versions from history) was deferred — the repo is private, the exposure window is short, and the rewrite would invalidate all SHAs.

**Files:** `.gitignore:55-63`; commit `df63fe4 chore(kelk): untrack private identity foundation material`.

---

## 5. Architecture Decisions Landed This Session

### 5.1 FCT056 ensemble/face vocabulary adopted

The vocabulary documented in FCT056 §2 supersedes the IG88011 tier framing and FCT046 failover-chain framing **for agent-internal cognition**. FCT046 remains authoritative for coordinator-level provider resilience (different problem). The terms: **flow, current, tide, turn, eddy pool, conductor, wash, ensemble agent, face**.

Discipline rule (per `ensemble_face_vocabulary.md` and FCT056 §1): the metaphor is concentrated in §1–§3.5 of FCT056; from §4 onward the terms are used operationally as technical vocabulary. Don't write "thought pools in the reflex face until the tide turns" in implementation docs — say "the reflex face consults the deliberative face."

The vocabulary is **scale-free**: it describes within-agent cognition (continuous flow) and across-room message flow (the pinball/ricochet view in §3.5) at compatible resolutions. The pinball view is fair game when the subject is workspace infrastructure; the flow view is the right view for agent-internal cognition.

### 5.2 MCP-server-as-consultant chosen as the wiring mechanism

Hermes's native `auxiliary:` config is a fixed schema with eight hardcoded keys, none of which is a generic dispatch surface. `mixture_of_agents_tool.py:63` hardcodes four OpenRouter models with no parameters. LiteLLM is complementary infra (the right answer for workspace-wide unified inference routing) but does not by itself give the agent a way to say "this next call goes to a different face."

The chosen mechanism is a Python MCP server that exposes one tool per non-reflex face. The reflex face calls `consult_deliberative(query, context?)` exactly the same way it calls `search_files`. The MCP server proxies to whatever endpoint backs that face (OpenRouter for 31B, future local models, etc.).

`scripts/face-consultant-mcp.py` (694 lines) is implemented. `test-face-consultant-mcp.py` is a 54-assertion smoke test that all pass. The server is **not yet wired** into IG-88's profile pending verification of `OPENROUTER_API_KEY` env passthrough to the MCP child process. That is Phase 2 of the FCT056 rollout.

### 5.3 FCT057 agent-aware message chunking — design only

FCT057 documents the `<<<MATRIX_BREAK>>>` marker convention with coordinator safety-net paragraph-boundary splitting. The agent emits the marker at semantic boundaries; the coordinator splits on the marker and falls back to recursive paragraph/sentence/word splitting if a single chunk still exceeds the Matrix event budget. UTF-8-safe slicing replaces the latent panic at `matrix_legacy.rs:241,547`.

**Implementation deferred** per Chris's direction. The bug is currently masked by the `max_tokens` ceiling (responses rarely approach Matrix's 30k char budget yet) but will become live once long responses stack.

### 5.4 Ensemble architecture is per-agent

Each of the three factory agents will have its own ensemble configuration. IG-88's initial ensemble (FCT056 §5):

| Face | Model | Venue | Trigger |
|---|---|---|---|
| reflex | Gemma 4 E4B 6-bit | local mlx-vlm-ig88 :41988 | every message, every tool cycle (default) |
| deliberative | Gemma 4 31B | OpenRouter via `consult_deliberative` MCP tool | tide-turn triggers in FCT056 §6 |
| memory | Qdrant / Graphiti | :41460 / :41440 MCP | "what do I already know about X?" |
| analyst | TBD | TBD | reserved, not Phase 1 |

Boot and Kelk will get analogous ensembles in Phase 4 of the FCT056 rollout, with role-appropriate deliberative faces (Boot: code-tuned model; Kelk: long-context reflective model).

The **resilient-node invariant** governs the design: for every face F in an ensemble, the agent must still be able to respond to a basic Matrix DM with F unreachable. Phase 3 smoke-tests this explicitly.

---

## 6. Durable Lessons (feedback memory captured)

The following entries were saved to `~/.claude/projects/-Users-nesbitt-dev-factory/memory/` during the session:

| File | Type | One-line summary |
|---|---|---|
| `feedback_agent_handoff_paths.md` | feedback | Always use `~/dev/factory`, never `~/factory` — small models cannot recover from path errors |
| `feedback_agent_handoff_accuracy.md` | feedback | Verify every path/port in handoff prompts exactly against disk before sending |
| `feedback_no_mid_task_restarts.md` | feedback | Never restart a Hermes daemon while the agent is mid-turn; check activity first |
| `ensemble_face_vocabulary.md` | project | The new FCT056 vocabulary and its usage discipline |
| `ig88_standalone_gateway.md` | project | IG-88 runs matrix-nio directly, not coordinator-routed; bug surface differs from Boot/Kelk |
| `ig88_trading_build.md` | project | Updated with overnight outcome and post-fix state |
| `hermes_phase4_daemon.md` | project | Updated to scope Phase 4 to Boot/Kelk only; IG-88 is on the standalone gateway pattern |

The discipline points across these entries cohere into one rule: **the small local models cannot recover from harness errors**, so the harness must be perfect before we hand them work. Path typos, port misses, mid-task restarts, silent provider re-routes, schema mismatches — all of them produce silent failures that look like the agent's fault but are not.

---

## 7. Commits Landed This Session

The commit log up to the start of this doc:

| SHA | Message |
|---|---|
| `df63fe4` | `chore(kelk): untrack private identity foundation material` |
| `715efca` | `fix(agents): correct workspace path typos in soul files and plans` |
| `bbfb86a` | `fix(factory): FCT055 overnight failure post-mortem and remediation` |
| `7c74f1b` | `feat(factory): FCT056 ensemble agents and face-consultant MCP server` |

A final end-of-session commit batch will include this FCT058 doc, FCT057 (chunking design), the rewritten SOUL.md files, the auxiliary-routing fixes in the Hermes profiles, the PREFIX protocol updates, the TERMINAL_CWD wrapper-script changes, the `max_tokens: 32768` profile additions, the Kelk timeline reconciliation, and the `.gitignore` updates.

---

## 8. Open Items and Follow-Ups

### 8.1 IG88015 recovery — pending

IG-88 needs to write its orientation report. The clarifying follow-up prompt is queued in `260408-handoff-prompts.md:197-230`. As of this writing, IG-88 has not yet completed the write.

**Placeholder:** Update this section with the result once IG-88 confirms the write landed (path, size, summary).

### 8.2 FCT057 chunking implementation — deferred

Design ready in FCT057. Implementation deferred per Chris's direction. The latent UTF-8 panic at `coordinator/src/matrix_legacy.rs:241,547` becomes reachable as soon as a response approaches 30k chars. Pre-fix, the `max_tokens=256` truncation kept responses well below that ceiling; post-fix (3.9), the bug is live but unobserved.

### 8.3 Face-consultant MCP wire-up — Phase 2 of FCT056

`scripts/face-consultant-mcp.py` (694 lines) is built and tested. Not yet registered in `~/.hermes/profiles/ig88/config.yaml` under `mcp_servers.consultants`. Pending verification that `OPENROUTER_API_KEY` is passed through to the MCP child process via the Hermes MCP launcher.

### 8.4 mlx-vlm PR #974 / #964 cherry-pick — deferred

Streaming-off workaround is live (3.2). The durable patch is to cherry-pick the two upstream PRs into our local `/Users/nesbitt/dev/vendor/mlx-vlm/` checkout and restart `mlx-vlm-{factory,ig88}`. Diffs available at `https://github.com/Blaizzy/mlx-vlm/pull/{974,964}.patch`. Both PRs include tests. Deferred — workaround is sufficient until upstream merges.

### 8.5 Kelk history purge — optional, deferred

The Kelk identity foundation material was previously committed and is now untracked. A `git filter-repo` rewrite would remove the previous versions from history. Deferred because the repo is private, exposure is bounded, and the rewrite would invalidate all SHAs.

### 8.6 FCT054 / FCT055 / IG88011 / FCT046 vocabulary retrofit — deferred

The older docs use tier/cascade/fallback framing in places. A mechanical pass to align them with the FCT056 ensemble/face/tide vocabulary should happen after the vocabulary has soaked in, not as part of FCT056 itself.

### 8.7 Coordinator HTTP timeout bump — deferred

Currently 120s. Should be raised to 300s to give large prefills (>30k tokens at ~660 tok/s = ~45s prefill alone) headroom. See 3.16.

### 8.8 Subprocess fallback path cleanup — deferred

`coordinator/src/agent.rs:409-422` has a latent provider-routing bug (3.17). Preferred fix is to remove the subprocess fallback entirely since the HTTP daemon path is canonical. Deferred.

### 8.9 Hermes SOUL.md ↔ agents/<name>/CLAUDE.md sync strategy — deferred

These files serve different readers (Hermes runtime reads SOUL.md, Claude Code reads CLAUDE.md) but share most of their content. A build script, symlink, or single-source-of-truth strategy would prevent drift. Deferred — the right answer is not yet obvious.

### 8.10 Plist adoption for Boot/Kelk wrappers — done late afternoon

The Boot and Kelk plists previously called `hermes-serve.py` directly. They have been updated to invoke the wrapper scripts so the preflight guards (3.8) and `TERMINAL_CWD` export (3.10) take effect.

---

## 8b. Corrections from Post-Session Log Review

The following bugs-fixed entries in §3 were documented as resolved but log evidence shows they were either not applied to the running daemons or remain partially broken. Original §3 text is preserved; corrections are recorded here.

### 3.1 addendum — RC-1 fix applied to disk, not confirmed in daemon

The `provider: custom` fix was written to all three profiles. However, Boot's daemon was still referencing `Nanbeige4.1-3B-8bit` at 01:00 on 2026-04-08 (`boot/logs/errors.log:21`), and Kelk was still hitting model-ID 400s through 13:19. **Writing a config does not reload a running daemon.** Neither Boot nor Kelk daemon restarts were confirmed with PID verification after the profile edits. The config is correct on disk; the daemons may not have been running it.

### 3.2 addendum — RC-2 streaming-off workaround is partial at best

The streaming-off workaround redirects to the non-streaming path. However, upstream PR #964 documents that `finish_reason="stop"` is hardcoded in **both** the streaming path (`server.py:1182`) and the non-streaming path (`server.py:1264`). IG-88's 600s timeouts at 13:13 and 13:39 — both after the workaround was applied — confirm the dead-loop was not stopped. The non-streaming path still emits `finish_reason=stop` when tool calls are present, Hermes still misinterprets it, and the loop still fires. **RC-2 is unresolved. Cherry-pick of PR #964 is the required fix, not just PR #974.**

### 3.9 addendum — `max_tokens: 32768` fix confirmed for IG-88, unconfirmed for Boot/Kelk

The end-to-end probe (count 1-100) was run against Boot's daemon. However, given the evidence that daemons weren't reliably restarted after config changes, the max_tokens fix may not be active in Boot and Kelk at this moment. Verify with a long-output probe after confirmed daemon restart.

### 3.11 addendum — auxiliary routing fix not yet effective in Kelk

Kelk's auxiliary routing fix was written to disk at ~13:00. The daemon restart at 13:00:27 was IG-88's daemon (to pick up the fix), not Kelk's. Kelk's errors.log shows model-ID 400s at 13:07 and 13:19 — both after the fix was applied to config. **Kelk's hermes-serve daemon has not been restarted with the new auxiliary routing config. Kelk's main inference provider is pinned correctly; its auxiliary subsystems are still routing to OpenRouter.** This is the current live failure mode for Kelk.

### 3.15 addendum — IG88015 recovery still pending

As of the time of this correction, IG88015 has not been written. The clarifying prompt was queued but the session outcome is unknown.

### New finding — asyncio crash in hermes-serve.py at 11:55

Not documented in §3 above. Kelk's `errors.log` at line 23 shows a full asyncio/aiohttp crash at **11:55:01** — `GracefulExit` → `CancelledError` in `hermes-serve.py:133` (`run_in_executor`) → `InvalidStateError: invalid state` on double-set of a waiter during shutdown. The crash was followed by a 40-minute recovery window (errors resume at 12:35). The traceback suggests the Kelk daemon is being killed mid-request and the shutdown sequence has a race condition in `hermes-serve.py:133`. This is not a Hermes upstream bug — it's in our local `scripts/hermes-serve.py`. The `run_in_executor` call at line 133 needs a cancellation guard during `GracefulExit`.

## 9. References

[1] FCT054, "Local E4B Model Consolidation — All Agents on Gemma 4 E4B 6-bit," factory docs, `docs/fct/FCT054 Local E4B Model Consolidation — All Agents on Gemma 4 E4B 6-bit.md`, Apr. 2026.

[2] FCT055, "IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening," factory docs, `docs/fct/FCT055 IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening.md`, Apr. 2026.

[3] FCT056, "Ensemble Agents and Face-Based Cognition — Architecture Proposal," factory docs, `docs/fct/FCT056 Ensemble Agents and Face-Based Cognition — Architecture Proposal.md`, Apr. 2026.

[4] FCT057, "Agent-Aware Matrix Message Chunking — Design Proposal," factory docs, `docs/fct/FCT057 Agent-Aware Matrix Message Chunking — Design Proposal.md`, Apr. 2026.

[5] FCT046, "Provider Failover Chain and Hermes Integration Architecture," factory docs, `docs/fct/FCT046 Provider Failover Chain and Hermes Integration Architecture.md`, Apr. 2026. (Partially superseded by FCT056 for agent-internal cognition; remains authoritative for coordinator-level provider resilience.)

[6] FCT052, "Hermes Agent Latency Fix — Phase 4 HTTP Daemon," factory docs, `docs/fct/FCT052 Hermes Agent Latency Fix.md`, Apr. 2026.

[7] IG88011, "Cloud Model Bake-Off Results," `agents/ig88/docs/ig88/IG88011 Cloud Model Bake-Off Results.md`, Apr. 2026. (T1/T2/T3 tier framing superseded by FCT056 ensemble/face vocabulary; bake-off data remains authoritative.)

[8] P. Cuadra et al., "mlx-vlm PR #974 — Strip tool-call markup from streamed delta.content," GitHub. [Online]. Available: https://github.com/Blaizzy/mlx-vlm/pull/974

[9] P. Cuadra et al., "mlx-vlm PR #964 — Set finish_reason to 'tool_calls' when the model emits tool calls," GitHub. [Online]. Available: https://github.com/Blaizzy/mlx-vlm/pull/964

[10] Hermes Agent documentation — Providers, NousResearch. [Online]. Available: https://hermes-agent.nousresearch.com/docs/integrations/providers

[11] Hermes Agent documentation — Configuration, NousResearch. [Online]. Available: https://hermes-agent.nousresearch.com/docs/user-guide/configuration

[12] Matrix Specification, "m.room.message event size limit." [Online]. Available: https://spec.matrix.org/latest/client-server-api/#size-limits
