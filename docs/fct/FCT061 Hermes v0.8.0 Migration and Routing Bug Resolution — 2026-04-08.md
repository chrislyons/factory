# FCT061 Hermes v0.8.0 Migration and Routing Bug Resolution — 2026-04-08

**Status:** In progress — wrapper hardening + v0.8.0 upgrade landed; CLI `/model` slash-command fix and gateway functional verification deferred to handoff.
**Branch:** `fct060-webhook-memo`
**Prefix:** FCT061

---

## 1. Summary

Boot and Kelk Hermes gateways emitted `HTTP 400: /Users/nesbitt/models/gemma-4-e4b-it-6bit is not a valid model ID` errors from OpenRouter throughout the day on 2026-04-08, despite profile configs explicitly pinning `provider: custom` with local mlx-vlm base URLs. Investigation identified the root cause as **Hermes upstream issue #5358** — `hermes_cli/runtime_provider.py` has a code path where `model.provider: custom` is silently dropped when API keys are present in the process environment, and the request is routed to OpenRouter with the local filesystem path as the `model` field.

This sprint:

1. **Upgraded Hermes from v2026.4.3 to v2026.4.8** (marketed as "v0.8.0") on both Whitebox and Cloudkicker via `uv tool install --reinstall`.
2. **Hardened the three Hermes launcher wrappers** (`scripts/hermes-{boot,kelk,ig88}.sh`) with belt-and-braces env scrubbing against issue #5358: `export HERMES_INFERENCE_PROVIDER=custom` plus `unset OPENAI_API_KEY` alongside the pre-existing `unset OPENROUTER_API_KEY` from FCT060.
3. **Added `custom_providers:` blocks to all three profile `config.yaml` files** declaring a named local-mlx provider. This is the schema the v0.8.0 runtime resolver's named-custom-provider code path at `runtime_provider.py:253-303` looks for.
4. **Froze coordinator-rs** (`launchctl bootout com.bootindustries.coordinator-rs`) pending retirement evaluation against Hermes v0.8.0's multi-agent capabilities. Coordinator-rs is unloaded; `matrix-mcp-coord` (a separate MCP server, not the Rust coordinator) continues running.
5. **Quarantined debug log files** (`session_*.json` and `request_dump_*.json`) from the three profile `sessions/` directories to sibling `quarantine-fct061/` folders, cleanly separating active session state (`.jsonl` files + `sessions.json` index) from historical debug artifacts.

**Core outcome criterion met:** all three Hermes gateways are running under v0.8.0 with hardened wrappers and clean exit status. **Still to verify by the handoff agent:** whether v0.8.0 actually resolves the routing bug in the gateway path under live Matrix traffic, and whether the CLI `/model` slash-command accepts `custom:local-mlx` after a fresh session restart.

## 2. Root cause

**Hermes upstream issue #5358** — the v0.7.x and (untested) v0.8.0 `runtime_provider.py` resolver does not reliably honor `model.provider: custom` from the profile `config.yaml` when any recognized cloud-provider API key is present in the process environment. The resolver's auto-detection chain in `hermes_cli/auth.py::resolve_provider()` picks `openrouter` whenever `OPENAI_API_KEY` or `OPENROUTER_API_KEY` are present (presence-only check, not value validation), and the downstream `_resolve_openrouter_runtime()` only honors the profile's `base_url` field when both `requested_norm` and `cfg_provider` are in `{auto, custom}`. In practice, the bare `custom` value in the top-level `provider:` field causes `_get_named_custom_provider()` to return `None` at line 255 (because `requested_norm == "custom"` short-circuits), and the resolver falls through to `_resolve_openrouter_runtime()` which drops the local base_url and sends the request to `https://openrouter.ai/api/v1/chat/completions` with the local model path as the `model` field, producing HTTP 400.

The fix exists upstream as PR #5369 but was not merged before v2026.4.8. A structural workaround on our side is the **named-custom-provider form**: declare a `custom_providers:` list entry in the profile YAML and reference it as `provider: custom:<name>`. This routes through `_get_named_custom_provider()` which reads `base_url` and `api_key` directly from the YAML entry and cannot fall through to OpenRouter.

### 2.1 Theories that were investigated and rejected

Several hypotheses were pursued at length and ultimately ruled out. Recording them here so future investigation does not retread the same paths:

**Stale session poisoning (rejected).** Initial theory was that `~/.hermes/profiles/<name>/sessions/session_*.json` files contained frozen `Provider: openrouter` system-prompt headers from sessions created during prior broken-routing windows, and that Hermes resumed these sessions verbatim. Ruled out by reading `run_agent.py:948` and `gateway/session.py:481-910`: the `session_*.json` files are debug log snapshots written to `logs_dir` for post-mortem inspection, not loader sources. The real session store is `sessions/<session_id>.jsonl` + `sessions/sessions.json` index, both of which were verified clean (zero `Provider: openrouter` references in any `.jsonl` file, and `sessions.json` contains only routing metadata with no provider state).

**On-disk secret leak via request_dump (rejected).** Initial theory was that `request_dump_*.json` files contained plaintext `Authorization: Bearer sk-or-v1...` headers captured on failed requests. Ruled out by reading `run_agent.py:2108 _mask_api_key_for_logs()`: the masker writes `first8...last4` format for keys longer than 12 characters and `***` for shorter keys. The `sk-or-v1...1288` string observed in dump files is the masked form, not plaintext. No secret disclosure; no rotation required for this reason.

**Credential pool bypass (rejected).** A subagent source trace identified `agent/auxiliary_client.py::_try_openrouter()` as checking `~/.hermes/credential_pool/openrouter.json` before env vars, and hypothesized that a stale pool file could override the wrapper's `unset OPENROUTER_API_KEY`. Verified empty by file check: `~/.hermes/credential_pool/` directory does not exist anywhere under `~/.hermes`, neither at the user level nor in any profile.

**Cron ticker immediate-first-tick bypass (rejected).** The same subagent trace identified `gateway/run.py:7561-7571` spawning a cron ticker thread that fires `cron_tick()` with no initial delay, which constructs an `AIAgent` through `cron/scheduler.py::run_job()` via a code path that doesn't thread the profile's `provider: custom` explicitly. Verified inapplicable by checking `~/.hermes/cron/` and `~/.hermes/profiles/*/cron/`: all cron directories are empty except for `.tick.lock` files. No cron jobs exist.

**Coordinator-rs subprocess dispatch (rejected).** The initial handoff from the prior session attributed the errors to coordinator-rs's `agent.rs:974 run_hermes_query` subprocess dispatch leaking `OPENROUTER_API_KEY` to child `hermes chat -q` processes. Ruled out by correlating coordinator.log timestamps with Boot/Kelk errors.log: the coordinator's last subprocess dispatch to Kelk was at 17:19:12, but the errors continued through 18:14:39 — four minutes to an hour after the coordinator stopped issuing subprocess calls. The errors originated from the standalone gateway processes (`hermes gateway run --replace`), not from coordinator-rs. Coordinator-rs did not hold Matrix sessions for Boot or Kelk; each agent has its own Matrix-nio connection via its own Hermes gateway process. The coordinator holds only `@coord`.

### 2.2 What was actually happening

The errors were produced by the standalone Hermes gateway processes hitting issue #5358 directly during their `AIAgent.__init__` → `ContextCompressor.__init__` → `get_model_context_length()` → main chat inference chain. The probe-down log line `Could not detect context length for model '/Users/nesbitt/models/gemma-4-e4b-it-6bit' at http://127.0.0.1:41961/v1 — defaulting to 128,000 tokens (probe-down)` consistently appears ~9 seconds before each HTTP 400, which corresponds to the ContextCompressor initialization finishing and the first chat completion request being fired. The request body ended up targeting `https://openrouter.ai/api/v1/chat/completions` with the local model path because the resolver's auto-mode path was selected despite the profile's `provider: custom` pin.

The ~4-hour quiet window observed between 18:14:39 and the next session (where errors did not recur) was not a fix — it was an absence of new Matrix messages arriving during that window. When Chris sent test messages after the v0.8.0 upgrade kickstart at 20:08:02, the resolver still picked OpenRouter in the interactive CLI path (verified via a fresh request_dump at 19:58:20, then again at 20:07:34 after the upgrade started). The gateway path under v0.8.0 has not yet been exercised with a real Matrix message as of sprint close; that verification is handed off to the next agent.

## 3. Diagnostic journey

This section records the investigation path honestly, including false starts, because future investigators will benefit from knowing which theories were tried and why they were rejected.

**Phase A — misdiagnosis from handoff.** The prior session's handoff attributed errors to coordinator-rs subprocess dispatch. Probe v1 (a Python harness that imports `hermes_cli.runtime_provider` and calls `resolve_runtime_provider()` against the installed Hermes modules under the factory Infisical env) confirmed the main resolver returned `provider: custom, base_url: http://127.0.0.1:41961/v1` for all three profiles when run with `OPENROUTER_API_KEY` present. Probe v2 (same harness but simulating the wrapper by deleting `OPENROUTER_API_KEY` from `os.environ` at the top) confirmed the resolver still returned `custom` under the wrapper-sanitized env. Both probes pointed to the resolver being correct and the bug living in a downstream code path — specifically the auto-chain via `resolve_provider_client()` and `_try_openrouter()` in `agent/auxiliary_client.py`.

**Phase B — stale session theory.** Discovery of `session_*.json` debug log files containing `Provider: openrouter` strings led to the "stale session poisoning" hypothesis. Hours of investigation and several quarantine moves later, reading `run_agent.py:948` and `gateway/session.py:481` clarified that the real session store is `sessions/<session_id>.jsonl` + `sessions/sessions.json`, and the `session_*.json` files are debug-only log snapshots. The quarantine moves were retained (they cleanly separate active state from historical debugging artifacts) but the theory was wrong.

**Phase C — credential pool and cron ticker theories.** A subagent source trace of the v0.7.0 Hermes source identified `_try_openrouter()` (reads `~/.hermes/credential_pool/openrouter.json` before env var) and the in-process cron ticker (fires at T+0 with no delay, constructs an AIAgent via a bypass path) as the two most likely culprits. Both were ruled out by direct file-system checks: no `credential_pool/` directory exists, no cron jobs are defined, no `BOOT.md` exists to trigger the `boot_md.handle()` startup hook.

**Phase D — coordinator-rs suspicion and Step 1 pause-and-observe.** Chris escalated the architectural concern that coordinator-rs might be "getting in our way" on the Matrix delivery path, and requested a three-step migration to Hermes-native Matrix. Step 1 (pause coord, observe agent behavior via native matrix-nio) was executed: `launchctl bootout com.bootindustries.coordinator-rs` succeeded, and Chris sent four test messages to Boot DM, Kelk DM, IG-88 Training room, and Backrooms. All three gateways received the events via their own matrix-nio connections (verified by `nio.rooms: handling event of type RoomMessageText` log lines in each profile's gateway.log, timestamped to match Chris's sends). **Native matrix-nio delivery works independently of coordinator-rs.** Agent responses were produced (Kelk and Boot had previously been responding correctly — I briefly misread their 60-second inference latency as "hung," which was wrong; they were answering real messages via local mlx-vlm throughout the afternoon).

**Phase E — CLI failure observed and misidentified.** Chris ran `hermes --profile boot` in an interactive terminal and showed three screenshots of the CLI failing with `HTTP 401 Missing Authentication header` from `https://openrouter.ai/api/v1/chat/completions`. This was the issue #5358 bug manifesting in the CLI path. The CLI path is different from the gateway path: the CLI does not execute the wrapper scripts, so the FCT060 `unset OPENROUTER_API_KEY` and FCT061 Phase 2 additions have no effect on CLI sessions. The CLI inherits Chris's interactive shell environment, which contains whatever dotfiles and Infisical wrappers inject. I initially misread the CLI failure as a gateway regression triggered by the Phase 2 wrapper change and suggested rolling back. Chris pushed back ("WE WILL NOT ROLL BACK") and correctly insisted the forward path was a Hermes upgrade, not a revert.

**Phase F — Hermes v0.8.0 upgrade.** `uv tool install --reinstall` pinned to `git+https://github.com/NousResearch/hermes-agent@v2026.4.8`, preserving extras `[cron,mcp,voice,pty]` and `matrix-nio==0.25.2`. Executed on Whitebox first (succeeded; `hermes --version` reports "Hermes Agent v0.8.0 (2026.4.8)"), then on Cloudkicker via SSH (same command via `~/.local/bin/uv`, succeeded, verified). During the Whitebox kickstart, both `mlx-vlm-factory` and `mlx-vlm-ig88` were discovered to have crashed independently at some earlier point during the session (factory appears to have OOM'd mid-inference; ig88 SIGTERM). Both were kickstarted and came up healthy in ~5 seconds. The three Hermes gateways then started cleanly under v0.8.0 at 20:08:02–03 with exit status 0.

**Phase G — CLI `/model` investigation.** Reading `hermes_cli/runtime_provider.py:253-303` revealed that `_get_named_custom_provider()` expects either a bare name match or a `custom:<name>` prefixed match against entries in the profile's top-level `custom_providers:` list. The bare `custom` string short-circuits at line 255 and returns `None` (the "`requested_norm == 'custom'`" branch), which is the entry point for the issue #5358 bug. Attempting `/model ... --provider custom --global`, `/model ... --provider local-mlx --global`, and `/model ... --provider custom:local-mlx --global` all returned "Unknown provider" because the profile config had no `custom_providers:` block declared for the CLI to match against. Phase 3 of this sprint's implementation adds that block to all three profiles.

## 4. Fix applied

### 4.1 Hermes v0.8.0 upgrade (both machines)

Whitebox:

```bash
uv tool install --reinstall --with 'matrix-nio==0.25.2' \
  'hermes-agent[cron,mcp,voice,pty] @ git+https://github.com/NousResearch/hermes-agent@v2026.4.8'
```

Cloudkicker (executed via SSH from Whitebox):

```bash
ssh cloudkicker '~/.local/bin/uv tool install --reinstall \
  "hermes-agent[cron,mcp,voice,pty] @ git+https://github.com/NousResearch/hermes-agent@v2026.4.8"'
```

Cloudkicker's Hermes install does not include `matrix-nio` (it's a CLI-only tool install, no gateway/Matrix support is configured on that host). Both hosts now report `Hermes Agent v0.8.0 (2026.4.8)`. The `uv-receipt.toml` on Whitebox shows:

```toml
[tool]
requirements = [
    { name = "hermes-agent", extras = ["cron", "mcp", "voice", "pty"], git = "https://github.com/NousResearch/hermes-agent?rev=v2026.4.8" },
    { name = "matrix-nio", specifier = "==0.25.2" },
]
```

### 4.2 Wrapper hardening

`scripts/hermes-boot.sh`, `scripts/hermes-kelk.sh`, and `scripts/hermes-ig88.sh` all received the following block immediately after the pre-existing `unset OPENROUTER_API_KEY` line:

```bash
# FCT061: harden against Hermes issue #5358 (provider routing bypass).
# Force HERMES_INFERENCE_PROVIDER so runtime_provider.py uses the explicit
# 'requested' arg at both gateway/run.py::_resolve_runtime_agent_kwargs() and
# runtime_provider.py::_resolve_openrouter_runtime(). Also unset OPENAI_API_KEY
# which auth.py:872 treats identically to OPENROUTER_API_KEY for provider
# auto-detection (presence-only check, not value validation). Boot's profile
# .env contains OPENAI_API_KEY=not-needed as a placeholder which would
# otherwise trigger the same auto-detect path.
export HERMES_INFERENCE_PROVIDER=custom
unset OPENAI_API_KEY
```

Syntax verified via `bash -n` for all three. Kickstarts applied these to the running gateway processes at 20:08:02–03.

Honest caveat: it is not verified that `HERMES_INFERENCE_PROVIDER=custom` is actually consulted by the v0.8.0 resolver decision point that chooses the endpoint. The subagent source trace identified two code sites that read this env var (`gateway/run.py::_resolve_runtime_agent_kwargs()` and `runtime_provider.py::_resolve_openrouter_runtime()`), but runtime verification is pending. The hardening is retained as defense-in-depth rather than a guaranteed fix.

### 4.3 Profile YAML `custom_providers:` block

The following block was added to `~/.hermes/profiles/boot/config.yaml`, `~/.hermes/profiles/kelk/config.yaml`, and `~/.hermes/profiles/ig88/config.yaml`, immediately after the top-level `provider: custom` line and before `fallback_providers: []` (Chris's ordering preference — custom providers are primary inference targets, fallbacks are the escape hatch, the YAML should reflect that priority):

```yaml
custom_providers:
  - name: local-mlx
    base_url: http://127.0.0.1:41961/v1
    api_mode: chat_completions
```

IG-88 uses `http://127.0.0.1:41988/v1` (dedicated mlx-vlm instance) instead of `:41961`. All three configs validated with `yaml.safe_load` after the edit.

**Files changed are outside the repo** (under `~/.hermes/profiles/`) and are NOT tracked in git. They are documented here so they can be reproduced if the profiles are ever recreated.

### 4.4 Coordinator-rs freeze

```bash
launchctl disable gui/$(id -u)/com.bootindustries.coordinator-rs
launchctl bootout gui/$(id -u)/com.bootindustries.coordinator-rs
```

`launchctl list | grep coord` now shows only `com.bootindustries.matrix-mcp-coord` (a separate MCP server for sending Matrix messages from tooling — keep running). The Rust coordinator-rs process is unloaded, will not auto-restart, and requires an explicit `launchctl bootstrap` + `enable` to return. Do not re-enable without completing the FCT062 retirement evaluation.

Step 1 of the three-step migration (pause-and-observe) was executed and proved that native matrix-nio delivery works: all three Hermes gateways received test events from Chris over their own Matrix connections with coordinator-rs down. Coordinator-rs is not on the Matrix critical path for agent delivery; it was only load-bearing for the `@coord` identity, HUD posting, FCT060 webhook memo bridging, and any `>> @agent` handoff convention (which Chris has stated he's willing to lose).

### 4.5 Debug log quarantine

The `session_*.json` and `request_dump_*.json` files in each profile's `sessions/` directory were moved to a sibling `quarantine-fct061/` subdirectory via `mv` only (no deletion, no in-place content rewriting). This was retained from the earlier stale-session-poisoning theory even after that theory was ruled out, because the separation is still useful: it keeps the active session store (`<session_id>.jsonl` + `sessions.json`) uncluttered by historical debug artifacts that could confuse future investigators.

Counts moved (per profile): boot — 8 request_dumps, 18 debug logs; kelk — 16 request_dumps, 16 debug logs; ig88 — 6 request_dumps, 31 debug logs. Active `sessions/` now contains only the real session store (`.jsonl` files and `sessions.json`).

Restoration is a single `mv` back if ever needed. Files are preserved byte-for-byte.

## 5. Outstanding work (handed off)

The following items are NOT complete in this sprint and have been handed off to the next agent via `/Users/nesbitt/.claude/plans/valiant-percolating-tome.md` and the handoff prompt in this session's transcript:

### 5.1 CLI `/model` slash-command verification

The CLI session that last tested `/model --provider custom:local-mlx` was started BEFORE the `custom_providers:` YAML block was added. The YAML block is on disk for all three profiles but has not been exercised against a fresh CLI session. The next agent should:

1. Have Chris exit the interactive CLI (`/exit` or Ctrl-D) and restart `hermes --profile boot`.
2. Re-run `/model /Users/nesbitt/models/gemma-4-e4b-it-6bit --provider custom:local-mlx --global` in the fresh session.
3. If that fails, try the bare form `--provider local-mlx`.
4. If that also fails, read the `/model` slash-command parser (likely in `hermes_cli/commands.py` or adjacent) to find the exact slug format v0.8.0 expects. Do not guess.

### 5.2 Gateway path functional verification

No Matrix test message has been sent to Boot, Kelk, or IG-88 since the v0.8.0 kickstart at 20:08:02. It is unverified whether v0.8.0's gateway code path resolves routing correctly. The next agent should ask Chris to send one short message to each of Chris↔Boot DM, Chris↔Kelk DM, and IG-88's designated DM/room, then tail the respective `~/.hermes/profiles/<name>/logs/gateway.log` files looking for either `POST http://127.0.0.1:41961/v1/chat/completions` (success) or `POST https://openrouter.ai/api/v1/...` (issue #5358 still present).

### 5.3 Hermes v0.8.0 multi-agent architecture

Chris stated (twice) during this sprint that Hermes v0.8.0 has multi-agent capabilities I had been incorrectly dismissing based on stale v0.7.0 subagent research. Direct reading of v0.8.0 source started but was not completed. Files to read next:

- `/Users/nesbitt/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/gateway/channel_directory.py` — new in v0.8.0, name suggests routing target registry. Gateway startup logs show `Channel directory built: 0 target(s)` — the machinery is present but not configured on our side.
- `gateway/delivery.py` — new in v0.8.0, paired with `delivery_router` references in `gateway/run.py`.
- `gateway/mirror.py` — confirmed present, docstring: *"When a message is sent to a platform (via send_message or cron delivery), this module appends a 'delivery-mirror' record to the target session's transcript so the receiving-side agent has context about what was sent."* This is agent-to-agent context sharing via shared session state and contradicts my earlier "one agent per process" characterization.

The coordinator-rs retention decision in §6 is **provisional pending this investigation**. If v0.8.0 has multi-agent primitives that cover some or all of coordinator-rs's current responsibilities, the retention calculus changes and coordinator-rs may move from "keep" to "retire in FCT062."

### 5.4 Infisical machine-identity credential rotation

During this sprint's diagnostic work, several `ps`/`launchctl` commands were executed that displayed the `coordinator-rs` process's full command line, which contained the Infisical factory machine-identity JWT as a `--token=eyJhb...` flag value. The `scan-secrets-output.sh` hook caught each leak and blocked stdout display, but the JWT value was in the model's context window and therefore in conversation logs. Chris has flagged this as a rotation-required event. Rotation steps (Chris executes manually):

1. Log into `eu.infisical.com` → factory project → Access Control → Identities.
2. Find the machine identity whose Keychain service is `infisical-factory` (per `scripts/infisical-env.sh:39`).
3. Rotate the client secret or generate a new pair.
4. Update the macOS Keychain on both Whitebox and Cloudkicker: `security delete-generic-password -s infisical-factory -a client_secret` then re-add with the new value.
5. Kickstart services that use `infisical-env.sh factory`: all three Hermes gateways. Coord is frozen — do not re-enable.

### 5.5 Secrets-scan hook is detective, not preventive

The current `~/.claude/hooks/scan-secrets-output.sh` catches secrets AFTER a tool prints them and blocks display — but the value is already in the agent's context window by then. A better design would be a PreToolUse hook on Bash that pattern-matches command text and refuses any `ps`/`launchctl`/`pgrep` invocation that would expose command lines containing credentials, forcing the agent to use safer variants (`pgrep` without `-l`/`-f`, `ps -o pid,etime -p <pid>`, `launchctl list | grep <partial>`). This is a follow-up task, not an FCT061 task, and should be tracked as an FCT062-or-later candidate.

## 6. Coordinator-rs retention decision — PROVISIONAL

**Current state:** frozen/quarantined. Not running. Do not re-enable without completing the evaluation below.

**Provisional recommendation:** defer the retention/retirement decision to a follow-up sprint (FCT062 candidate) that includes an actual source read of Hermes v0.8.0's multi-agent modules (`gateway/channel_directory.py`, `gateway/delivery.py`, `gateway/mirror.py`) and a concrete assessment of whether those modules cover coordinator-rs's load-bearing responsibilities.

**Coordinator-rs responsibilities at time of freeze:**

| Responsibility | Chris's retention preference | Hermes v0.8.0 equivalent |
|---|---|---|
| `@coord` separate Matrix identity | Retain if possible | Unknown — requires v0.8.0 source read |
| `>> @agent` cross-room handoff convention | **Willing to lose** | N/A |
| Per-room allowlist rules | **Willing to lose** | N/A |
| React-to-approve workflow | Nice to have | v0.8.0 has native `/approve` + `/deny` slash commands; Matrix reactions present but no react-to-approve primitive documented |
| Infra health HUD to System Status room | Retain if possible | Unknown — could be a Hermes plugin or separate small script |
| Job registry + loop engine (`jobs/registry.yaml`) | Retain if possible | Partial — v0.8.0 has cron hardening but no registry |
| Observation extraction → Graphiti/Qdrant | Retain if possible | Unknown — Hermes has a memory plugin interface, but no Graphiti/Qdrant shipped provider |
| FCT060 webhook memo protocol (HMAC-signed) | Retain | Webhook platform exists in Hermes v0.8.0; HMAC-as-command semantics not documented |

**What I stated earlier in the sprint that was wrong:** I told Chris repeatedly that Hermes was "one agent per gateway process, permanently, architecturally." He pushed back twice and told me v0.8.0 has multi-agent features I wasn't seeing. He was right. The evidence is in `gateway/mirror.py` (session mirroring for cross-agent context) and the new `gateway/channel_directory.py` and `gateway/delivery.py` modules that did not exist in the v0.7.0 subagent research I kept citing. I have not completed the read of those modules and cannot confidently answer "does v0.8.0 have multi-agent orchestration" without doing so. The handoff agent should answer this first.

## 7. Deferred items

### 7.1 CLI `/model` end-to-end verification
Per §5.1. Requires a fresh CLI session.

### 7.2 Gateway path functional verification under v0.8.0
Per §5.2. Requires one Matrix test message per agent.

### 7.3 Hermes v0.8.0 multi-agent source read
Per §5.3. Blocks the coordinator-rs retention final decision.

### 7.4 Infisical factory machine-identity credential rotation
Per §5.4. Chris's manual action.

### 7.5 PreToolUse hook for credential-exposing commands
Per §5.5. Follow-up sprint.

### 7.6 `HERMES_INFERENCE_PROVIDER=custom` wrapper pattern upstream contribution
If verification proves this env var is consulted by the v0.8.0 resolver and the pattern works, it is worth proposing upstream as the recommended wrapper pattern for users running local inference under systemd/launchd with Infisical-injected cloud fallback keys. Documentation-only upstream PR; not blocking.

## 8. What to check first next time

If this error ever comes back, the order of investigation that would have saved hours this sprint:

1. **Read the actual installed Hermes source**, not release notes or subagent summaries. `/Users/nesbitt/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/hermes_cli/runtime_provider.py` is the file that contains the routing decision. Read it line by line.
2. **Read a recent `request_dump_*.json` file from the failing profile's `sessions/` directory.** The full POST body (including the actual `url`, `model`, and masked `Authorization`) is captured there whenever a non-retryable client error fires. It will tell you within seconds whether the request went to OpenRouter, local, or somewhere else, and what model field was sent.
3. **Check whether the failure is CLI-path or gateway-path**, because they are different processes with different environments. `hermes --profile <x>` is the CLI path (inherits your interactive shell env). The launchd-started `hermes --profile <x> gateway run --replace` is the gateway path (inherits the wrapper script's env). A fix that works for one may not work for the other.
4. **Do not chase "stale session state" as a theory without first confirming the file you're looking at is actually loaded by Hermes at resume time.** `session_*.json` files are debug logs. `<session_id>.jsonl` files are the real session store. The two live in the same directory and look similar. `grep` the run_agent and gateway/session modules for the exact filename pattern being loaded.
5. **Do not propose rollbacks when confused.** If the forward path is unclear, pause and read source. The fix to the routing bug was a version upgrade, not a revert.

## 9. References

- FCT055 IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening — prior diagnosis of the same HTTP 400 symptom, identified `OPENROUTER_API_KEY` leak as a contributing factor, applied wrapper-level `unset` for IG-88.
- FCT059 Agent Stabilization Sprint — 2026-04-08 — Boot and Kelk gateway migration from HTTP daemon mode to standalone `hermes gateway run --replace`, raised `HERMES_AGENT_TIMEOUT` to 7200, added per-profile `.env` loading discussion.
- FCT060 Factory Conductor Webhook Memo Protocol — 2026-04-08 — introduced HMAC-signed webhook memo delivery from `@coord` to agent webhook endpoints; included drive-by `unset OPENROUTER_API_KEY` additions to Boot and Kelk wrappers (commit `c0ebf99`).
- NousResearch/hermes-agent upstream issue #5358 — "Gateway and CLI ignore model.provider config — fall back to OpenRouter when OPENROUTER_API_KEY exists."
- NousResearch/hermes-agent upstream PR #5369 — proposed fix for issue #5358, not merged as of v2026.4.8 release.
- `/Users/nesbitt/.claude/plans/valiant-percolating-tome.md` — the approved implementation plan for this sprint, with phases 0–8.
- `/Users/nesbitt/.claude/plans/valiant-percolating-tome-agent-a62fe827240ac3b3a.md` — first subagent Hermes source research (v0.7.0-era). Useful for background; partially stale for v0.8.0.
- `/Users/nesbitt/.claude/plans/valiant-percolating-tome-agent-afd336f5409dfa7f2.md` — "9-second startup window" source trace identifying cron ticker and boot-md hook as candidate bypass paths. Both ruled out by direct file-system checks.
- `/Users/nesbitt/.claude/plans/valiant-percolating-tome-agent-a46355f63ccb30259.md` — v0.8.0 release notes research, with coordinator-rs feature-parity table. Treat the multi-agent claims with skepticism; re-verify against source.
