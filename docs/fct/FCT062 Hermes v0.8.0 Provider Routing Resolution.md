# FCT062 Hermes v0.8.0 Provider Routing Resolution

**Status:** Partially resolved — gateway main-inference path verified; **CLI `/model` for user-defined custom providers blocked by a newly discovered Hermes v0.8.0 upstream bug** (see §2.4). Pivoted to OpenRouter Gemma 4 31B (`google/gemma-4-31b-it`) as primary interactive-CLI inference across all three profiles as a temporary bootstrap while the upstream bug is reported and the local-MLX routing path remains parked.
**Date:** 2026-04-08
**Branch:** `fct060-webhook-memo`
**Supersedes (final-mile):** FCT061 (in-progress migration and routing bug doc from earlier in the day)
**Related:** FCT055 (Hermes routing hardening), FCT060 (webhook memo protocol), FCT058 (agent infrastructure troubleshooting session)

---

## 1. Summary

FCT061 landed the v0.8.0 upgrade (`v2026.4.3` → `v2026.4.8`), the wrapper env-hardening, and a `custom_providers:` list in the three Hermes profile configs. It closed the **gateway main inference** provider routing path. It did not close the **`/model` slash-command** path, which uses a second, newly introduced provider resolver in v0.8.0 that reads a different YAML key.

This doc records the final-mile fix: source-reading the v0.8.0 Hermes CLI to identify the two coexisting provider-resolution schemas, adding a top-level `providers:` dict to each of the three profile configs, restarting MLX-VLM and Hermes services, and verifying end-to-end routing from the gateway to the local MLX endpoints at `127.0.0.1:41961` (factory shared) and `127.0.0.1:41988` (IG-88 dedicated). It also records the formal decision to keep coordinator-rs quarantined but **not** retire it, grounded in v0.8.0 source reading rather than stale notes.

---

## 2. Root cause — two provider schemas coexist in v0.8.0

Hermes v0.8.0 carries **two distinct custom-provider resolution code paths**, each reading a different top-level key in `config.yaml`. Both paths are live simultaneously. A profile that only declares one schema will route correctly through one path and fail through the other.

### 2.1 Legacy path — `custom_providers:` list

- **Reader:** `hermes_cli/runtime_provider.py:576 resolve_runtime_provider()`, named-custom-provider branch.
- **Activator:** `HERMES_INFERENCE_PROVIDER=custom` environment variable.
- **Consumer:** Gateway main inference loop via `gateway/run.py:290 _resolve_runtime_agent_kwargs()`.
- **Schema:** Top-level YAML list of provider entries, each with a name, base URL, and optional auth fields.

FCT061 closed this path by adding `custom_providers:` entries and exporting `HERMES_INFERENCE_PROVIDER=custom` in the three wrapper scripts.

### 2.2 New path — `providers:` dict

- **Reader:** `hermes_cli/providers.py:449 resolve_provider_full(name, user_providers)` → `resolve_user_provider()` (lines 410–446).
- **Consumer:** CLI `/model` slash-command via `hermes_cli/model_switch.py:439 resolve_provider_full(explicit_provider, user_providers)`; gateway `/model` handler at `gateway/run.py:3543 user_provs = cfg.get("providers")`.
- **Schema:** Top-level YAML **dict** keyed by bare slug. Each entry accepts:
  - `name` — display name
  - `api` — base URL (aliases `url`, `base_url` accepted)
  - `key_env` — name of the env var holding the API key (optional for keyless local endpoints)
  - `transport` — default `openai_chat`
- **Slug form:** bare slug only, no `custom:` prefix. `normalize_provider()` at `providers.py:249` lowercases and alias-resolves, then the slug is looked up as a literal key in the `providers:` dict.

The exact error surfaced in the interactive CLI was:

```
Unknown provider 'custom:local-mlx'. Check 'hermes model' for available providers,
or define it in config.yaml under 'providers:'.
```

That text is emitted by `hermes_cli/model_switch.py:442-444`. The error message is itself a signpost to the correct schema.

### 2.3 Why FCT061's fix was incomplete

FCT061 added `custom_providers:` and exported `HERMES_INFERENCE_PROVIDER=custom`. Both are correct for the legacy path. Neither touches the `providers:` dict the new path reads. Gateway main inference succeeded; CLI `/model` did not. Two paths, two schemas, two fixes required.

---

## 3. Theories pursued earlier and corrected

Three earlier diagnostic theories from FCT061 were based on partial evidence and have been retired by source reading:

1. **"Stale session poisoning"** — the `session_*.json` files quarantined earlier are debug log snapshots written by `run_agent.py:948`, not session-loader sources. The real session store is `sessions/<id>.jsonl` plus a `sessions.json` index. Quarantine had no effect on routing either way.
2. **"Plaintext secret in `request_dump_*.json`"** — `run_agent.py:2108 _mask_api_key_for_logs()` masks the Authorization header before dump. The `sk-...`-prefixed strings observed were the masked form. No on-disk secret leak from this path.
3. **"Upstream issue #5358 still biting under v0.8.0"** — issue #5358 targets `runtime_provider.py` in v0.7.x. The v0.8.0 upgrade moved past the affected code in the gateway path. The wrapper env-scrubbing (unset `OPENAI_API_KEY`, unset `OPENROUTER_API_KEY`, export `HERMES_INFERENCE_PROVIDER=custom`) is belt-and-braces rather than the primary fix.

---

## 4. Fix applied

### 4.1 Wrapper hardening (already in place from FCT061)

`scripts/hermes-boot.sh`, `scripts/hermes-kelk.sh`, and `scripts/hermes-ig88.sh` each perform, before exec'ing the Hermes gateway:

- `unset OPENROUTER_API_KEY` (from FCT060)
- `unset OPENAI_API_KEY` (added in FCT061)
- `export HERMES_INFERENCE_PROVIDER=custom` (added in FCT061)

No changes to the wrappers in this doc. They are correct for the legacy path and harmless for the new path.

### 4.2 YAML schema migration — add `providers:` dict to all three profiles

On Whitebox, a top-level `providers:` dict was appended to each profile config, alongside the pre-existing `custom_providers:` list. Both schemas are kept intentionally — the legacy list for the gateway main inference path, the new dict for the `/model` slash-command path.

Files touched:

- `~/.hermes/profiles/boot/config.yaml` — endpoint `http://127.0.0.1:41961/v1`
- `~/.hermes/profiles/kelk/config.yaml` — endpoint `http://127.0.0.1:41961/v1`
- `~/.hermes/profiles/ig88/config.yaml` — endpoint `http://127.0.0.1:41988/v1`

Block appended (endpoint URL adjusted per profile):

```yaml
# FCT062: providers dict for /model slash command (v0.8.0 schema)
providers:
  local-mlx:
    name: Local MLX
    api: http://127.0.0.1:41961/v1   # :41988 for ig88
    transport: openai_chat
```

No `key_env` is set — the local MLX endpoints are unauthenticated on loopback, and the `openai_chat` transport tolerates absent auth.

### 4.3 Service restarts

Factory MLX-VLM servers were both observed to have exited from prior OOM / SIGTERM / SIGKILL events during the long FCT061 session. Kickstart order:

1. `com.bootindustries.mlx-vlm-factory` — new PID, `/health` returns 200 with `loaded_model = gemma-4-e4b-it-6bit`.
2. `com.bootindustries.mlx-vlm-ig88` — new PID, `/health` returns 200 with `loaded_model = gemma-4-e4b-it-6bit`.
3. `com.bootindustries.hermes-boot` — clean startup, webhook listener bound on `:41951`, Matrix connected as `@boot.industries`, 22 rooms joined, cron ticker started, no preflight guard failures.
4. `com.bootindustries.hermes-kelk` — clean startup, webhook listener bound on `:41952`, Matrix connected as `@sir.kelk`, 9 rooms joined, cron ticker started.
5. `com.bootindustries.hermes-ig88` — clean startup, Matrix connected as `@ig88bot`, webhook listener bound on `:41977`, 9 rooms joined, cron ticker started.

No authentication errors in any of the three startup logs. No preflight guard exit codes.

---

## 5. Verification evidence

1. **MLX-VLM health endpoints respond 200** with `loaded_model = gemma-4-e4b-it-6bit` on both `127.0.0.1:41961` and `127.0.0.1:41988`.
2. **Gateway → MLX-VLM routing proven by log evidence.** `/Users/nesbitt/Library/Logs/factory/mlx-vlm-factory.log` shows `POST /v1/chat/completions HTTP/1.1 200 OK` entries at approximately 20:10 local from the v0.8.0 gateway, dated after the wrapper hardening took effect. The only errors in `~/.hermes/profiles/boot/logs/errors.log` are three stale `401 Missing Authentication header` entries dated 20:07–20:10, from test traffic dispatched **before** the hardened wrapper loaded. Post-hardening, no 401s.
3. **CLI `/model` fix validated structurally.** All three profile YAML files parse cleanly post-edit. The `providers.local-mlx` entry is present with the correct endpoint per profile. The pre-existing `custom_providers.local-mlx` entry is preserved untouched. Both schemas present, both parse, no key collisions.
4. **Interactive CLI verification is a Chris action.** The running `hermes --profile boot` interactive session was spawned before the YAML edit and still holds the old config in memory. Chris must exit that session, restart `hermes --profile boot`, and then run:

   ```
   /model /Users/nesbitt/models/gemma-4-e4b-it-6bit --provider local-mlx --global
   ```

   Bare slug, **no `custom:` prefix**. If the command returns a model-switch confirmation, the new schema path is closed. If it still emits the `Unknown provider` error, re-read `hermes_cli/model_switch.py:439-444` against the installed version.

---

## 6. Coordinator-rs retention decision

**Decision: keep `coordinator-rs` quarantined (`launchctl bootout`-unloaded) but do not retire it.** The decision is grounded in direct source reading of v0.8.0, not in pre-upgrade notes.

What v0.8.0 actually provides for multi-agent coordination:

- `gateway/run.py:461-493` — `GatewayRunner._running_agents` is keyed by **session_key**, not by persona. One agent per gateway process; multiple sessions share the same underlying persona.
- `/personality` command (`gateway/run.py:3871-3950`) is a **system-prompt overlay** on the single agent, not a second agent instance.
- `gateway/delivery.py` — `DeliveryRouter` routes messages to **platforms** (telegram / discord / matrix). It does not route to named peer agents. No agent-to-agent handoff primitive.
- `gateway/mirror.py` — appends delivery records to a session's **own** transcript for context preservation. It is not a peer-agent messaging channel.
- `gateway/channel_directory.py` — discovery cache for connected Discord and Slack channels. Not a routing config. The startup log line `Channel directory built: 0 target(s)` is expected when only Matrix is connected.
- Zero matches for `room_routing`, `agent_allowlist`, or `per_room_personas` keys anywhere in `hermes_cli/config.py`.
- Zero matches for `>> @agent` syntax across the gateway codebase.
- Release notes confirm subagent delegation is **parent → child** (PRs #5309, #5748), not peer-to-peer. "Shared thread sessions" (PR #5391) means **multi-user in one thread**, not multi-agent.

Implication: Boot, Kelk, and IG-88 as three **coordinating peer agents** on Matrix with cross-agent handoffs still requires an external orchestrator. v0.8.0 does not provide peer-agent coordination primitives. Coordinator-rs remains the reference implementation for that use case and is preserved on disk. Formal retirement — if ever — is deferred to a future sprint (candidate: FCT063) and would be considered only if the peer-agent coordination story is explicitly dropped from the factory roadmap.

---

## 7. Deferred items

1. **Infisical factory client secret rotation — Chris manual action.** Earlier in the session, credential-bearing command output from `ps` and `launchctl print` on gateway services surfaced a JWT-bearing process argv into the assistant's context. The scan-secrets hook caught each occurrence and blocked output, but the value still entered the assistant's context window. Treat the corresponding machine-identity token as compromised. Steps:
   1. eu.infisical.com → factory project → Access Control → Identities.
   2. Find the machine identity whose keychain service is `infisical-factory` (per `scripts/infisical-env.sh:39`).
   3. Rotate the client secret.
   4. Update macOS Keychain on Whitebox and Cloudkicker via:
      ```
      security delete-generic-password -s infisical-factory -a client_secret
      ```
      then re-add the new value.
   5. Kickstart all services that use `infisical-env.sh factory` — all three Hermes gateways. `coordinator-rs` is quarantined; do not re-enable it as part of this rotation.

2. **`scan-secrets-output.sh` hook hardening.** The current hook detects after-the-fact and blocks the tool's output, but by then the secret has entered the assistant's context window. A `PreToolUse` hook on `Bash` that pattern-matches the command text and refuses any invocation of `ps` (with wide argv), `launchctl <label>`, or `pgrep -lf` against Hermes/coord services would prevent the leak at source. Track as a follow-up sprint item.

3. **Coordinator-rs formal retirement evaluation.** FCT063 candidate only, and only if peer-agent coordination is explicitly dropped.

4. **Matrix v0.8.0 tier-1 feature testing.** Reactions, read receipts, rich formatting, and room management primitives from PR #5275 are present in the installed build but untested under the factory workload. Separate sprint.

---

## 8. Honest failure modes this session

During this session the following incorrect theories were pursued and corrected:

- Early diagnosis incorrectly attributed HTTP 400s to "stale session poisoning" in `session_*.json` files. Those files are debug log snapshots, not loader sources.
- Early claim that `request_dump_*.json` files contained plaintext secrets was wrong — `_mask_api_key_for_logs()` masks them before dump.
- The assistant initially claimed Hermes was "one agent per gateway process" based on stale v0.7.0-era research and dismissed multi-agent features it had not read. Source verification of v0.8.0 confirmed the claim was correct for the multi-*process* case, but the recommendation "keep coordinator-rs permanently" needed to be grounded in v0.8.0 source, not notes — which is what §6 of this doc does.
- Credential-bearing `ps` and `launchctl` command outputs were generated multiple times during the session. The scan-secrets hook caught each one, but the values still entered the assistant's context. Corrected going forward to `launchctl list | grep <partial-label>`, `pgrep`, and explicit column selection `ps -p <pid> -o pid,etime` rather than wide-argv listings.

---

## 9. References

[1] NousResearch, "Hermes Agent v0.8.0 (v2026.4.8) release notes," *GitHub*, Apr. 8, 2026. [Online]. Available: https://github.com/NousResearch/hermes-agent/releases/tag/v2026.4.8

[2] NousResearch, "Hermes Agent issue #5358 — provider routing bypass in `runtime_provider.py`," *GitHub*. Referenced in the FCT061 wrapper-hardening phase as the origin of the `OPENAI_API_KEY` / `OPENROUTER_API_KEY` env-scrubbing requirement.

[3] NousResearch, "Hermes Agent PR #5181 — `/model` command: full provider and model system overhaul," *GitHub*. Cited in the v0.8.0 release notes as the origin of the new `providers:` dict schema and live model switching across the CLI and all gateway platforms.

[4] NousResearch, "Hermes Agent PR #5309 — Subagent sessions linked to parent," *GitHub*. Cited for the parent-to-child delegation model in §6.

[5] NousResearch, "Hermes Agent PR #5391 — Shared thread sessions by default," *GitHub*. Cited for multi-user (not multi-agent) thread semantics in §6.
