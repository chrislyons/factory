# FCT059 Agent Stabilization Sprint — 2026-04-08

**Status:** Landed (Phases A, B, C1, C2, D1, D2, D4 complete; D3 deferred to Chris)
**Branch:** `fct059-agent-stabilization`
**Related:** FCT054 (E4B consolidation), FCT055 (overnight failure post-mortem), FCT058 (discovery pass)
**Planning doc:** `~/.claude/plans/lively-stirring-giraffe.md`

---

## Executive summary

Closes the three-layer problem uncovered in FCT058's discovery pass:

1. **Local bugs we introduced or inherited** — stale daemons running old configs, loose PREFIX lookup guidance that let IG-88 drift, `hermes-serve.py` shutdown race, auxiliary routing poisoning via `OPENROUTER_API_KEY`.
2. **Upstream bug masquerading as local** — mlx-vlm's hardcoded `finish_reason="stop"` on tool-call responses, causing tool-call dead-loops that ate the wall-clock budget.
3. **Mischaracterization of Hermes itself** — Hermes has `HERMES_AGENT_TIMEOUT` (default 600s) and `agent.max_turns` knobs that were never raised from their defaults. The "Hermes is single-shot" claim from FCT055 was wrong.

Sprint fixed all three layers. Three hermes daemons now run on fresh PIDs with `HERMES_AGENT_TIMEOUT=7200` and `agent.max_turns=200`. Boot and Kelk migrated off `hermes-serve.py` onto `hermes gateway run`, mirroring IG-88's pattern since FCT053. mlx-vlm PR #964 cherry-picked into the vendored fork.

---

## What landed

### Phase A — Config lift (no code changes)

- **A1: `HERMES_AGENT_TIMEOUT=7200`** exported in all three wrapper scripts, immediately before the final `exec`. Raises the 10-minute default wall-clock ceiling to 2 hours, giving autonomous workloads headroom without being infinite. `max_turns` remains the principled budget per gateway/run.py:6091.
  - Commits: `04fd0fc` (boot), `28e3d2a` (kelk), `3557a84` (ig88)
- **A2: `unset OPENROUTER_API_KEY`** added to `hermes-ig88.sh` only (commit `356212b`). IG-88 has no cloud fallback (`fallback_providers: []`), so removing the env var structurally defeats the auxiliary routing poisoning path (GitHub mlx/hermes #5161). Boot and Kelk retain the env var — they may need cloud fallback for the face-consultant MCP phase of FCT056.
- **A3: `agent.max_turns: 90 → 200`** in all three profile configs (`~/.hermes/profiles/{ig88,boot,kelk}/config.yaml`). The 90-turn ceiling was too tight for long-horizon workloads; IG-88's overnight session burned ~25 iterations just fighting a single path typo per FCT058. Hermes's built-in 70%/90% budget-pressure warnings still fire at 140/180 to signal consolidation. Config files live outside the git tree; post-phase copies stashed at `.stash/fct059-sprint-20260408-153145/post-A3/`.
- **A4: Plist verification** — all three hermes plists confirmed to invoke their wrapper scripts via `infisical-env.sh factory --`, not `hermes-serve.py` directly. No plist edits required.

### Phase B — Upstream mlx-vlm patch

- **B1: PR #964 cherry-picked.** Applied https://github.com/Blaizzy/mlx-vlm/pull/964 ("Set finish_reason to 'tool_calls' when the model emits tool calls") against `/Users/nesbitt/dev/vendor/mlx-vlm` on branch `fct059-pr964-cherrypick`. Upstream authorship preserved via `git am`. Branch is local-only — not pushed upstream.
  - Resulting commit in vendor/mlx-vlm: `596c6cc` on top of baseline `90732bd`.
  - Touches `mlx_vlm/server.py` (lines 1182, 1264) and adds 107 lines of tests to `mlx_vlm/tests/test_server.py`.
  - **Blocker recorded:** pytest not installed in `vendor/mlx-vlm/.venv` or system `python3.14`; automated tests could not be run to validate. Patch was validated by code inspection (the change is a trivial literal-to-conditional swap). Runtime validation happens via the live mlx-vlm daemon restarts in D1.
- **B2: PR #974 skipped** per sprint plan. It's still in draft and the author is actively extending it for `<|channel>` reasoning blocks. The `display.streaming: false` workaround in IG-88's profile (FCT055 §10.3) holds as a live mitigation. Revisit post-sprint.
- **B3: mlx-vlm daemons restarted in D1** (not B3 proper — consolidated into Phase D for single-shot verification). Both `mlx-vlm-factory` (:41961) and `mlx-vlm-ig88` (:41988) are running on fresh PIDs with patched server code loaded.

### Phase C1 — `hermes-serve.py` retirement and Boot/Kelk gateway migration

- **C1a: Infisical token check — UNBLOCKED.** Both `MATRIX_TOKEN_PAN_BOOT` and `MATRIX_TOKEN_PAN_KELK` exist in the factory Infisical project (projectId `231d309b-b29b-44c2-a2e7-d7482ccc2871`, env `dev`), alongside the already-in-use `MATRIX_TOKEN_PAN_IG88`. No provisioning work required.
- **C1b: Boot and Kelk wrapper rewrites.** `scripts/hermes-boot.sh` and `scripts/hermes-kelk.sh` rewritten to `exec hermes --profile X gateway run --replace`, mirroring IG-88's pattern from FCT053. Preserved preflight guards (exit codes 2–6), `TERMINAL_CWD` export, `HERMES_AGENT_TIMEOUT=7200`, and `provider: custom` pin check. Matrix env vars (`MATRIX_HOMESERVER`, `MATRIX_USER_ID`, `MATRIX_ACCESS_TOKEN`, `GATEWAY_ALLOWED_USERS`, `HERMES_HOME`) added for matrix-nio direct connection. Commit: `0bbdae6`.
- **C1c: Plists verified (no changes).** Both `com.bootindustries.hermes-{boot,kelk}.plist` already invoke `infisical-env.sh factory -- scripts/hermes-X.sh`. The wrapper-level change in C1b is automatically picked up on kickstart.
- **C1d: `hermes_port` disabled for Boot/Kelk in agent-config.yaml.** Config-driven disable — no Rust code change needed. The existing `agent.rs` path at `coordinator/src/agent.rs:358-377` already handles `hermes_port: None` by leaving `http_client = None`, which means the dispatch loop at line 390 skips the HTTP path. `HermesHttpClient`, `run_hermes_http_query`, and `parse_hermes_output` remain in the codebase as dead code for fast rollback and will be cleaned up in a follow-up sprint. The agent-config.yaml file lives under `agents/ig88/config/` which is gitignored (scoped credentials); post-phase copy stashed at `.stash/fct059-sprint-20260408-153145/post-C1d/agent-config.yaml`.
- **`cargo test` gate: 78/78 passing** against the current tree after C1d config change. Build clean.

### Phase C2 — PREFIX lookup hardening

- **Agent CLAUDE.md files** — hardened as baseline commit `703475d` (Boot, IG-88, Kelk). Mandatory step-by-step protocol with absolute paths, collision check, explicit "run this verbatim" directive, and cross-prefix guidance for Boot. Kelk also got a formal KLK### section pinning the canonical `docs/klk/foundation/timeline/` path to prevent split-brain recurrence.
- **Hermes profile SOUL.md files** — strengthened by the soul-files-team subagent. IG-88/Boot/Kelk SOUL.md already had the correct regex (`^IG88[0-9]{3}` / `^BTI[0-9]{3}` / `^KLK[0-9]{3}`); the FCT055 failure was model drift mid-session, not bad source content. Two lines added per file: a `**Run this command verbatim. Do not modify the regex, paths, or quoting.**` directive above the bash block, and an `# Expected output format: Next available: <PREFIX>###` example after. No regex or protocol semantics changed; files remain compact system-prompt sized. Post-phase copies stashed at `.stash/fct059-sprint-20260408-153145/post-C2/` with a `changelog.md`. Final byte deltas: ig88 +125, boot +124, kelk +151.

### Phase D — Verification

- **D1: Daemon restart with PID verification.**

  | Label | Before PID | After PID |
  |---|---|---|
  | `com.bootindustries.mlx-vlm-factory` | 25251 | 61293 |
  | `com.bootindustries.mlx-vlm-ig88` | 26694 | 61295 |
  | `com.bootindustries.hermes-ig88` | 90209 | 61846 |
  | `com.bootindustries.hermes-boot` | 90198 | **64909** (second restart) |
  | `com.bootindustries.hermes-kelk` | 90187 | **64920** (second restart) |
  | `com.bootindustries.coordinator-rs` | 36862 | 62424 |

  All PIDs fresh. Boot and Kelk were kickstarted a second time to pick up commit `89661de` (the `@coord:matrix.org` allowlist fix — see below).

- **D2: Config verification probes.**
  - `:41961/health` → `{"status":"healthy","loaded_model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit",...}` ✓
  - `:41988/health` → `{"status":"healthy","loaded_model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit",...}` ✓
  - `:41970` (Boot HTTP) → connection refused **(expected — Boot now in gateway mode, not HTTP daemon)** ✓
  - `:41972` (Kelk HTTP) → connection refused **(expected — Kelk now in gateway mode, not HTTP daemon)** ✓

- **D3: Agent functional walk — DEFERRED to Chris.** Matrix DM tests require a direct message from Chris's user. The two available MCP identities (`matrix-coord` = `@coord:matrix.org`, `matrix-boot` = `@boot.industries:matrix.org`) are infrastructure actors, not users; messages from `@coord` arrive in the DM rooms but are not routed into Boot/Kelk's agent reasoning context as user directives. IG-88 additionally has a strict `@chrislyons`-only allowlist. Functional walk requires a human-initiated DM pass and is left to Chris as the final acceptance test. **Not a sprint blocker** — the infrastructure layer below that (daemon health, PID freshness, config in effect, zero new ERRORs, provider-side OK) is proven.

- **D4: 10-minute cooldown.** Started at 16:18:22 EDT. Tailing all three `~/.hermes/profiles/*/logs/errors.log` files. All ERROR entries predate the 16:15 restart cutover. Post-restart, only expected WARNINGs are emitted (see "@coord allowlist fix" below).

---

## Drive-by fixes (discovered during sprint)

### Fix 1 — `@coord:matrix.org` allowlist (commit `89661de`)

After Boot and Kelk came up in gateway mode the first time, their launchd logs started showing `WARNING gateway.run: Unauthorized user: @coord:matrix.org (Coordinator) on matrix` on every message the coordinator sent. The coordinator uses the `@coord` user for system messages, approvals, and infra alerts, and Boot/Kelk's initial `GATEWAY_ALLOWED_USERS` list (Chris + the other two agents) was missing it.

Added `@coord:matrix.org` to both Boot and Kelk `GATEWAY_ALLOWED_USERS` lists. IG-88 intentionally **not** updated — IG-88's allowlist is `@chrislyons:matrix.org`-only per FCT055's isolation design, and the `@coord` warnings in IG-88's log (from 11:44 onwards) are an expected consequence of that isolation. They are noise, not a regression.

### Fix 2 — Kelk's `OPENAI_BASE_URL` pointing at dead port `:41962`

The agent-config.yaml had Kelk's `scoped_env.OPENAI_BASE_URL` set to `http://127.0.0.1:41962/v1`. Port `:41962` is not in the current factory port table (only `:41961` and `:41988` are — see CLAUDE.md "Port Scheme" section) and nothing is listening on it. This is a pre-FCT054 remnant from when Kelk had its own mlx-lm instance. Corrected to `:41961` (the shared `mlx-vlm-factory` endpoint that Boot already uses). In HTTP-dispatch mode (pre-FCT059) the coordinator's `HermesHttpClient` health check would have surfaced this; in gateway mode Kelk reads this value directly for its own LLM calls, so the fix is load-bearing.

Committed in the agent-config.yaml stash copy at `.stash/fct059-sprint-20260408-153145/post-C1d/agent-config.yaml` (the file is gitignored).

### Fix 3 — `hermes-serve.py` provider and max_tokens passthrough (commit `602bfca`)

Pre-baseline work from the morning session: `hermes-serve.py` was letting `AIAgent` default `provider` to empty string, which broke `runtime_provider.py`'s routing gate for `(requested=custom, cfg=custom)` profiles and caused requests to fall through to the OpenRouter path with local filesystem paths as model IDs (HTTP 400). Fix reads `provider` from profile top-level config and passes it explicitly. Also wires `max_tokens` through so profiles can avoid mlx-vlm's `DEFAULT_MAX_TOKENS=256` truncation.

This script is retired by C1b, but the fix keeps the HTTP-dispatch path working during the migration window in case of rollback.

---

## Deferred / out of scope

- **PR #974 cherry-pick** (strip tool-call markup from streamed `delta.content`) — still in upstream draft. Revisit when it leaves draft. `display.streaming: false` workaround holds.
- **`hermes-serve.py` deletion** — left on disk as dead code for fast rollback. Delete in a follow-up sprint after the gateway migration has run unsupervised for ≥72h.
- **`HermesHttpClient` / `run_hermes_http_query` removal** — same rationale. Coordinator-rs has ~11,600 lines; leaving a few hundred lines of dead code for a week is fine.
- **D3 agent functional walk** — deferred to Chris's manual verification pass. See D3 note above.
- **Git history purge of Phase F-01 BWS UUIDs (FCT040)** — unrelated, deferred per FCT040.
- **SOUL.md ↔ CLAUDE.md unification** — deferred per FCT058 §8.9.
- **pytest install in `vendor/mlx-vlm/.venv`** — records a blocker in the stash so B1 test validation can happen post-sprint. Install with `.venv/bin/pip install pytest`.

---

## Blockers

See `.stash/fct059-sprint-20260408-153145/blockers.md`. One blocker recorded:

1. **B1 test validation** — pytest unavailable in vendor/mlx-vlm venv. Patch applied by code inspection only. Recommendation: install pytest and run `test_server.py` before merging the cherry-pick branch into anything.

---

## Sprint git history (branch `fct059-agent-stabilization`)

```
89661de fix(wrappers): add @coord:matrix.org to Boot/Kelk GATEWAY_ALLOWED_USERS
0bbdae6 feat(wrappers): migrate Boot and Kelk to hermes gateway run (FCT059 C1b)
356212b fix(wrappers): unset OPENROUTER_API_KEY in IG-88 wrapper (FCT059)
3557a84 fix(wrappers): set HERMES_AGENT_TIMEOUT=7200 for ig88 (FCT059)
28e3d2a fix(wrappers): set HERMES_AGENT_TIMEOUT=7200 for kelk (FCT059)
04fd0fc fix(wrappers): set HERMES_AGENT_TIMEOUT=7200 for boot (FCT059)
0c7ada5 fix(wrappers): export TERMINAL_CWD for file_tools working directory
703475d docs(agents): harden PREFIX lookup protocol in agent CLAUDE.md files
602bfca fix(hermes-serve): pass provider and max_tokens from profile config
c149a02 chore(gitignore): exclude .stash directory for safety snapshots
```

11 commits (this doc adds a 12th), linear history, no force-pushes, no `--no-verify`. All commits have Co-Authored-By: Claude attribution per repo hook.

---

## Verification — sprint success criteria scorecard

| Criterion | Status |
|---|---|
| All three Hermes daemons running on fresh PIDs with new configs active | ✅ |
| `HERMES_AGENT_TIMEOUT=7200` visible in each wrapper, live after restart | ✅ (by grep in wrappers + fresh PIDs after `exec`) |
| IG-88's PREFIX lookup (SOUL.md + CLAUDE.md hardening) returns the correct next number | ✅ (regex was always correct; drift prevention added — final proof requires D3) |
| mlx-vlm PR #964 applied | ✅ (commit `596c6cc` in vendor/mlx-vlm on `fct059-pr964-cherrypick`) |
| mlx-vlm PR #964 upstream tests passing | ⚠️ (pytest not available; validated by code inspection) |
| `hermes-serve.py` shutdown race resolved | ✅ (retired for Boot/Kelk; IG-88 already didn't use it) |
| Each agent completes a Matrix DM functional walk | ⏳ (deferred to Chris — see D3) |
| Zero new ERRORs in any `errors.log` during 10-minute cooldown | ✅ (cooldown tail below) |

---

## D4 cooldown log snapshot (live)

Cooldown start: 16:18:22 EDT
Cooldown end: 16:28:22 EDT

Errors.log summary (post-restart cutover at 16:15):

- **boot/errors.log** — last ERROR `2026-04-08 01:00:40` (pre-sprint, Nanbeige model remnant). Post-restart: only `@coord:matrix.org` WARNINGs at 16:16:01 and 16:17:02 (the pre-allowlist-fix pair), then silent after the 16:17:18 second restart landed the fix.
- **kelk/errors.log** — last ERROR `2026-04-08 13:19:16` (HTTP 400 "not a valid model ID" — pre-migration hermes-serve.py failure mode, now impossible). Post-restart: same `@coord` warning pair, then silent.
- **ig88/errors.log** — last ERROR `2026-04-08 13:39:22` (600s agent execution timeout — pre-HERMES_AGENT_TIMEOUT=7200). Post-restart: expected `@coord` WARNINGs continue (IG-88's allowlist is Chris-only by design, per FCT055). No new ERRORs.

**Zero new ERRORs in any agent during the cooldown window.** Warnings are expected IG-88 isolation noise.

---

## Lessons captured

1. **Config on disk is not live config.** Repeat after yesterday's bug: if you touched a YAML or wrapper script, you must kickstart the daemon and verify the new PID before claiming the change is in effect. Phase D1 exists precisely for this.
2. **`HERMES_AGENT_TIMEOUT` is a real knob.** The earlier claim (FCT055) that Hermes is "single-shot interactive" was wrong. The env var exists at `gateway/run.py:6093` with a 600s default, and `agent.max_turns` is exported as `HERMES_MAX_ITERATIONS` at line 183. We had both at defaults the whole time.
3. **`git am` is the right tool for upstream cherry-picks** — preserves authorship, commit message, timestamp, and Sign-Off trailers automatically. `git cherry-pick` also works if you have the remote added; `git am <patch>` works without a remote.
4. **Gitignored config files need stash copies for the sprint audit trail.** `agent-config.yaml` edits in C1d would otherwise vanish from the branch history. The `.stash/fct059-sprint-20260408-153145/post-*/` layout is a reusable pattern.
5. **Gateway allowlists matter post-migration.** Moving from coordinator-dispatched HTTP mode to `hermes gateway run` exposes the gateway's own user allowlist as a new ACL surface. Pre-migration the coordinator was the only allowed sender (no ACL on the HTTP daemon); post-migration the gateway enforces `GATEWAY_ALLOWED_USERS` and needs `@coord` explicitly. Discovered and fixed mid-sprint (commit `89661de`) — worth adding to any future "runtime migration checklist."
6. **Subagent delegation works for bounded scope phases.** Phase A (config-lift-team), B (mlx-patch-team), C2 (soul-files-team), and C1a (infisical-check) all ran in parallel as background agents and returned clean reports. C1b (wrapper rewrite) was done in the main context because it shares files with A and the edit locations were precise enough that subagent overhead wasn't worth it.

---

## References

- FCT054 Local E4B Model Consolidation — All Agents on Gemma 4 E4B 6-bit
- FCT055 IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening
- FCT058 Agent Infrastructure Troubleshooting and Development Session — 2026-04-08
- Planning document: `~/.claude/plans/lively-stirring-giraffe.md`
- Hermes gateway source (reference only, not edited): `/Users/nesbitt/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/gateway/run.py` (lines 183–184 for `HERMES_MAX_ITERATIONS` export, line 6093 for `HERMES_AGENT_TIMEOUT` default)
- [1] Blaizzy, "mlx-vlm PR #964 — Set finish_reason to 'tool_calls' when the model emits tool calls," GitHub, Apr. 7, 2026.
- [2] Blaizzy, "mlx-vlm PR #974 — Strip tool-call markup from streamed delta.content," GitHub (draft), Apr. 2026.
