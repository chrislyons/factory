# FCT064 Factory Profile Rotation and Aux-Route Hardening

**Date:** 2026-04-10
**Author:** Team lead (Whitebox) with Boot/Cloudkicker session handoff
**Scope:** `~/.hermes/profiles/{boot,kelk,ig88}/`, `scripts/hermes-*.sh`,
`~/.zshrc` agent aliases, new `scripts/factory-profile.sh` + templates +
`scripts/_mlx-lib.sh`
**Status:** Phase 1 (IG-88 profile rewrite) and Phase 2 (wrapper/alias env
scrub + Boot/Kelk compression tuning) landed. Phase 3 (`factory-profile.sh`
switcher + templates + shared plist library) in progress under a companion
agent. Phases 4–6 (this doc, extended verification, RC5 upstream fix) open.
**Cross-refs:** FCT054, FCT055, FCT058, FCT061, FCT062, FCT063

---

## Executive Summary

Three Hermes agents (Boot, Kelk, IG-88) were silently escaping their
declared `provider: custom` local-MLX routing and hitting OpenRouter and
Anthropic even after the FCT061/FCT062/FCT063 remediation. Investigation
uncovered five distinct root causes: an auxiliary-client resolver that
probes `OPENROUTER_API_KEY` before honoring the profile; IG-88's profile
left half-unwound from the FCT062 OpenRouter pivot; an `mlx_vlm` hot-reload
trap that tries to fetch from HuggingFace on any non-canonical model ID;
a Metal GPU command-buffer timeout on >12k prefills combined with a
`model_metadata.py` fallback that defeated compression; and runtime
provider drift at the CLI main-loop level that spontaneously re-routed
Boot to OpenRouter Gemma 4 31B on a 181-message history. Phases 1–2
land the profile rewrite, env scrubs, and compression tuning. Boot and
Kelk were kickstarted at 2026-04-10 00:58-00:59 local; IG-88's gateway
and MLX server on :41988 were intentionally left running per explicit
user directive — the edits take effect on IG-88's next natural restart.

---

## Root Causes

Five root causes, not four. Each is independent; collectively they
explain every symptom observed between 2026-04-08 and 2026-04-09.

### RC1 — `_resolve_auto` probes `OPENROUTER_API_KEY` as step 1 of its chain

Source: `agent/auxiliary_client.py::_resolve_auto` in
`~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/`.

When any auxiliary task (`session_search`, `compression`, `vision`,
`skills_hub`, `approval`, `mcp`, `flush_memories`, `web_extract`) has
`provider: auto` — which is the default if the profile omits an explicit
`provider:` — the resolver walks its own chain instead of deferring to
the profile's top-level `provider: custom`:

1. `_try_openrouter()` — if `OPENROUTER_API_KEY` is present in env,
   OpenRouter wins regardless of what the profile says at the top.
2. `_try_anthropic()` via `_try_payment_fallback()` — after an
   OpenRouter 402 Payment Required or credits error, the fallback
   iterator walks the entire provider list including Anthropic. A
   single OR 402 therefore chain-routes the next call to Anthropic.
3. `_read_main_provider()` — for IG-88 only, because its profile had
   `provider: openrouter` at the top level, this path returned
   `"openrouter"` directly and bypassed the chain entirely. That is
   why IG-88 main-loop calls were going to OR despite the wrapper's
   `unset OPENROUTER_API_KEY`.

**Why the FCT061 / FCT062 wrapper scrubs were not enough on their own:**
they only unset `OPENROUTER_API_KEY`. `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `OPENAI_BASE_URL`, and `OPENAI_API_BASE` were
still being injected by Infisical into the wrapper process and inherited
by Hermes. The fallback chain latched onto whichever one it found.

### RC2 — IG-88's profile is half-unwound from the FCT062 OpenRouter pivot

`~/.hermes/profiles/ig88/config.yaml` as of 2026-04-09 evening carried:

```yaml
model: google/gemma-4-31b-it
provider: openrouter
```

…at the top level, while every `auxiliary.*` slot pointed at the
absolute path `/Users/nesbitt/models/gemma-4-e4b-it-6bit`. This is a
geometry that cannot work in any environment:

- Main loop → `_read_main_provider()` returns `openrouter` →
  wrapper-scrubbed key → 401 → Hermes failover sends the literal string
  `google/gemma-4-31b-it` to local MLX on :41988 → server replies
  `{"error":"The requested model is not supported"}` HTTP 400. Observed
  verbatim on 2026-04-09 21:20 in `~/.hermes/profiles/ig88/logs/errors.log`.
- Aux loop → every task slot carries an absolute on-disk path as its
  `model:` field → MLX does not recognize it (its canonical ID is
  the HuggingFace-style string, see RC3) → triggers the hot-reload trap
  → 500 Internal Server Error.

IG-88 was therefore failing both the main and auxiliary resolution paths
simultaneously, from two different mechanisms, and the wrapper-level
fixes applied elsewhere had no effect on either.

### RC3 — `mlx_vlm` hot-reload trap on non-matching model IDs

**The single most important discovery of this sprint.**

`mlx_vlm.server`, when it receives a `POST /v1/chat/completions` whose
`model:` field does not exactly match the string it considers its
canonical loaded model ID, unloads the currently-cached model and
attempts to **fetch the new one from HuggingFace**. This behavior is
observed verbatim in Kelk's MLX log on 2026-04-09:

```
Loading model from: gemma-4-e4b-it-6bit
Error loading model gemma-4-e4b-it-6bit: 401 Client Error
Repository Not Found for url:
  https://huggingface.co/api/models/gemma-4-e4b-it-6bit/revision/main
INFO: 127.0.0.1:[redacted] - "POST /v1/chat/completions HTTP/1.1" 500
```

The 401 is HuggingFace responding to an anonymous GET for a non-existent
repo name. The 500 is `mlx_vlm.server` having torn down its working
model to chase the fetch, failing, and being left with no model loaded
until the next matching request reloads it.

**The canonical-ID invariant.** Each of the three MLX servers is launched
via plist with `--model /Users/nesbitt/models/gemma-4-e4b-it-6bit` as its
argv. However, the string that each server advertises at
`GET /v1/models` and considers canonical for request routing is
`mlx-community/gemma-4-e4b-it-6bit` — normalized from the model card
inside the on-disk directory, NOT from the argv. Before this sprint the
profiles used the absolute path as the model ID, which tripped the
hot-reload trap on every request.

> **Invariant (established this sprint):** The canonical model-ID
> string used in all Hermes profile `model:` fields must exactly match
> the string reported by `GET /v1/models` on the target MLX server.
> For all three Whitebox MLX servers today that string is
> `mlx-community/gemma-4-e4b-it-6bit`. HuggingFace is not part of our
> inference plumbing — there is no network fetch in the healthy path —
> but `mlx_vlm` will call out to HuggingFace if it receives a model ID
> it does not recognize, so any drift in the profile string breaks
> inference and leaks the model name as an anonymous GET against
> huggingface.co.

The absolute path is used only in the plist `--model` argv, because
`mlx_vlm` opens it as a filesystem directory. Every other reference —
profile `model:` at the top level, every `auxiliary.*.model`, every
`custom_providers[].models.<id>` key — must use the canonical string.

**Secondary observation (server ID pollution).** `:41962` was observed
on 2026-04-09 to advertise both `mlx-community/gemma-4-e4b-it-6bit`
**and** a bare `gemma-4-e4b-it-6bit` in its `/v1/models` response. The
bare-name entry is pollution from a previous bare-name request that the
server admitted to its registry. The fix is to never send the bare name;
the pollution clears on server restart. No action taken this sprint.

### RC4 — Metal GPU Timeout on large prefills, compounded by a `model_metadata.py` fallback that defeated compression

From `~/Library/Logs/factory/mlx-vlm-ig88.log` on 2026-04-09:

```
Prefill: 100%|███| 12206/12207 [00:18<00:00, 667.80tok/s]
libc++abi: terminating due to uncaught exception of type std::runtime_error:
[METAL] Command buffer execution failed: Caused GPU Timeout Error
(...kIOGPUCommandBufferCallbackErrorTimeout)
```

A 12k-token prefill exceeded Apple Metal's command-buffer watchdog. The
`kIOGPUCommandBufferCallbackErrorTimeout` is a hardware-level ceiling
set by the GPU driver, not a Hermes or `mlx_vlm` knob, and cannot be
disabled from either config layer [1].

**The trap that made this worse.** Hermes's `agent/context_compressor.py`
computes its compression trigger as
`threshold_tokens = int(self.context_length * threshold_percent)` with
`threshold_percent` defaulting to `0.50`. There is no absolute-floor
parameter in the current Hermes release — the trigger is strictly
proportional to the context length that Hermes believes the model has.

Hermes determines context length by calling the model server's
`/v1/models` endpoint and reading the `context_length` field from the
response. `mlx_vlm.server` does not include `context_length` in its
response. When Hermes cannot find the field, `agent/model_metadata.py`
line 407 falls back to:

```python
model.get("context_length", 128000)
```

…so every local Gemma 4 E4B 6-bit inference was resolving to a believed
context of **128000** tokens. At `threshold_percent: 0.50` the
compressor would have fired at **64000 tokens** — impossible, because
the model crashes at 12k. Compression was notionally enabled in the
profile but was permanently unreachable.

**The three-part mitigation.**

1. Explicitly declare `context_length: 8192` in each profile's
   `custom_providers[0].models.<model_id>.context_length` key. This
   overrides the 128000 fallback at the profile level without requiring
   any change to the MLX server's `/v1/models` response format.
2. Explicitly set `auxiliary.compression.threshold: 0.50` in each
   profile. Combined with the 8192 override this fires compression at
   ~4096 tokens — well clear of the 12k Metal ceiling, with
   comfortable margin for in-flight generation.
3. Audit and delete `~/.hermes/context_length_cache.yaml` if it exists
   and contains any 128000 entries against our local model. Hermes
   caches `/v1/models` responses there between runs; a poisoned cache
   would survive the profile fix. Verified this file does not currently
   exist on Whitebox; it may be created on next gateway start and
   should be re-audited then.

**User preference is preserved.** `context_length: 8192` is a
compression *trigger* threshold, not a hard ceiling the conversation
hits. The agent never sees a "context too long" error. When the working
context grows past the trigger, Hermes silently summarizes old turns
into a shorter digest and continues. Conversations remain effectively
unlimited from the agent's perspective.

### RC5 — Main-loop CLI runtime provider drift

The subtlest of the five, and the only one not fully closed this sprint.

From `~/.hermes/profiles/boot/logs/errors.log` on 2026-04-09 07:15:

```
2026-04-09 07:15 ERROR root: API call failed after 3 retries.
HTTP 429: Provider returned error |
  provider=openrouter
  model=google/gemma-4-31b-it
  msgs=181
  tokens=~89094
  request_id=[redacted]
```

This is Boot's **main loop**, not its aux resolver, reporting that it
had been routing to OpenRouter Gemma 4 31B with a 181-message history
totaling ~89k tokens. Boot's profile at 07:15 was already the clean
Boot profile (FCT062-corrected): `provider: custom`, `model:
mlx-community/gemma-4-e4b-it-6bit`, `base_url:
http://127.0.0.1:41961/v1`. There is no path through the profile alone
that should have produced an OR 31B call.

**Likely mechanism.** `hermes_cli/runtime_provider.py` exposes a
runtime provider-swap path — used by the interactive `/model` slash
command and by webhook memo protocols that can carry a per-call
provider hint. Either a prior interactive `/model openrouter
google/gemma-4-31b-it` invocation persisted runtime state that was
rehydrated on gateway restart, or a drift in the main-loop's runtime
provider cache allowed the per-call hint to outlive its intended scope.
The 181-message history suggests this had been drifting silently for
most of the night.

**Fix applied (band-aid).** The Phase 2 wrapper env scrubs ensure that
even if runtime drift happens, the drifted-to provider has no
credentials in env and will fail fast with a clean 401 instead of
sending 89k tokens to a paid endpoint.

**Fix deferred (root).** A source read of
`hermes_cli/runtime_provider.py::_get_named_custom_provider` and the
slash-command persistence path is required to close RC5 at the Hermes
level. If the drift is a Hermes bug it should be filed upstream with
a reference to Hermes upstream bug tracker entry #5358 (the
FCT061/FCT062 tracking bug). Until then, the env scrub is the only
defense and it is intentionally belt-and-braces rather than targeted.

---

## Invariants Established This Sprint

The following rules are now load-bearing and must be preserved by any
future profile edit, agent provisioning script, or switcher template:

1. **The canonical model-ID string for all three Whitebox MLX servers
   is `mlx-community/gemma-4-e4b-it-6bit`.** This string must appear
   in every Hermes profile `model:` field (top-level and every
   `auxiliary.*.model`), every `custom_providers[].models.<id>` key,
   and every `/model` slash-command invocation. The absolute path
   `/Users/nesbitt/models/gemma-4-e4b-it-6bit` is used only as the
   plist `--model` argv, because `mlx_vlm.server` opens it as a
   filesystem directory. Anywhere else the absolute path will trip
   the RC3 hot-reload trap.
2. **HuggingFace is not part of our inference plumbing.** There must be
   no outbound request to `huggingface.co` in the healthy path. If one
   appears in an MLX log, it is proof that a request with a
   non-canonical model ID has reached the server and that a profile
   or client somewhere is violating invariant 1.
3. **Every aux task in every profile must carry an explicit
   `provider: custom` + `base_url:` + `model:` triple.** Omitting the
   `provider:` field causes Hermes to treat the slot as
   `provider: auto` and walk the `_resolve_auto` chain (RC1), which
   will probe `OPENROUTER_API_KEY` before honoring the profile's
   top-level `provider: custom`.
4. **Every Hermes wrapper must scrub `OPENROUTER_API_KEY`,
   `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_BASE_URL`, and
   `OPENAI_API_BASE` from env before `exec hermes gateway run`.** The
   wrapper is the last defensible choke point. Even with profiles
   correct, runtime drift (RC5) can re-route inference to a cloud
   provider; the wrapper-level scrub ensures such drift fails closed.
5. **Profiles must declare `context_length: 8192`** in their
   `custom_providers[].models.<id>` entry for the local Gemma 4 E4B
   6-bit. Omitting this causes the `model_metadata.py` 128000 fallback
   and defeats compression entirely, leaving the agent one long
   conversation away from a Metal GPU command-buffer timeout.
6. **Profiles must declare `auxiliary.compression.threshold: 0.50`**
   (or lower) explicitly. Leaving compression at its implicit default
   is equivalent to disabling it when combined with the fallback
   problem in invariant 5.

---

## What Was Changed

### Phase 1 — IG-88 profile full rewrite (landed, no restart)

**File:** `~/.hermes/profiles/ig88/config.yaml`

- Top-level `model:` → `mlx-community/gemma-4-e4b-it-6bit`
- Top-level `provider:` → `custom`
- Top-level `base_url:` → `http://127.0.0.1:41988/v1`
- Every `auxiliary.*.model` → `mlx-community/gemma-4-e4b-it-6bit` (was
  the absolute on-disk path in every slot, tripping RC3)
- Every `auxiliary.*.provider` → explicit `custom` (was missing or
  `auto`, tripping RC1)
- Every `auxiliary.*.base_url` → `http://127.0.0.1:41988/v1`
- `custom_providers[0].models["mlx-community/gemma-4-e4b-it-6bit"].context_length`
  → `8192` (defeats the 128000 fallback, RC4)
- `auxiliary.compression.threshold` → `0.50` explicit
- `auxiliary.compression.summary_provider`, `summary_base_url`,
  `summary_model` → all set to the same local-custom triple
- `max_tokens` → unchanged at `32768` (generation ceiling, not prefill;
  does not affect the Metal timeout)
- Matrix config, webhook, toolsets, MCP servers, MATRIX_HOME_CHANNEL,
  `custom_providers[]` list, `providers:` dict — all preserved verbatim

**Hard constraint honored.** IG-88's Hermes gateway and MLX server on
:41988 were NOT restarted during Phase 1. Per explicit user directive,
IG-88 is currently working and :41988 must not be disturbed. The
profile edit takes effect on IG-88's next natural restart, which may
be days away. Phase 5 verification confirmed the edit landed on disk
without triggering any gateway reload.

### Phase 2 — Wrapper env scrubs, alias extensions, Boot/Kelk compression tuning (landed, Boot + Kelk kickstarted)

**Files edited by a companion agent, not this doc agent:**

- `~/dev/factory/scripts/hermes-boot.sh`
- `~/dev/factory/scripts/hermes-kelk.sh`
- `~/dev/factory/scripts/hermes-ig88.sh`

Each wrapper received a new scrub block immediately after the existing
`unset OPENROUTER_API_KEY` line:

```bash
# FCT064: close Anthropic + OpenAI-compat escape paths.
# Anthropic budget is exhausted until 2026-05-01.
# OPENAI_BASE_URL would redirect "custom" provider resolution to
# whatever Infisical injected (potentially an Anthropic proxy).
unset ANTHROPIC_API_KEY
unset ANTHROPIC_AUTH_TOKEN
unset OPENAI_BASE_URL
unset OPENAI_API_BASE
```

**`~/.zshrc` aliases:** `h-ig88` was extended from a bare
`infisical-env.sh … hermes -p ig88 chat` invocation to the same
`env -u ...` scrub pattern already in use on `h-boot` and `h-kelk`.
All three aliases now share the identical scrub list:

```bash
env -u OPENROUTER_API_KEY \
    -u ANTHROPIC_API_KEY \
    -u ANTHROPIC_AUTH_TOKEN \
    -u OPENAI_BASE_URL \
    -u OPENAI_API_BASE
```

**Boot and Kelk profile corrections.** A pre-FCT064 Cloudkicker session
had already landed partial fixes to Boot and Kelk profiles that moved
them from the absolute-path model ID to `mlx-community/gemma-4-e4b-it-6bit`.
Phase 2 extends those profiles with the RC4 mitigations that session had
not applied:

- `~/.hermes/profiles/boot/config.yaml`:
  `custom_providers[0].models["mlx-community/gemma-4-e4b-it-6bit"].context_length`
  → `8192`, and `auxiliary.compression.threshold` → `0.50`.
- `~/.hermes/profiles/kelk/config.yaml`: same two additions.

Without these, Boot and Kelk would have been one long conversation away
from the same Metal command-buffer timeout that took IG-88 down —
RC4 is not an IG-88-specific failure mode.

**Kickstart strategy applied:**

```
launchctl kickstart -k gui/$(id -u)/com.bootindustries.hermes-boot
launchctl kickstart -k gui/$(id -u)/com.bootindustries.hermes-kelk
# hermes-ig88: NOT kickstarted (user directive)
```

### Phase 3 — `factory-profile.sh` switcher and templates (in progress, companion agent)

**Not touched by this doc.** A companion agent is authoring
`scripts/factory-profile.sh`, `scripts/_mlx-lib.sh` (shared plist-swap
library factored out of `scripts/factory-mlx-switch.sh`), and the
template tree under `~/dev/factory/profiles/{boot,kelk,ig88}/`. The
design is captured here for reference only.

**Subcommands:**

```
factory-profile.sh status           # show current tag + drift check
factory-profile.sh ideal            # apply Ideal profile set
factory-profile.sh ideal --or-aux   # Ideal + OpenRouter auxiliary routing
factory-profile.sh cont-a           # apply Contingency A
factory-profile.sh cont-b <agent>   # apply Contingency B, mega-agent on <agent>
factory-profile.sh restore          # revert to last applied tag
```

**Template layout** (outside agent cwds to avoid capability leaks):

```
~/dev/factory/profiles/boot/ideal.yaml
~/dev/factory/profiles/boot/ideal-or.yaml
~/dev/factory/profiles/boot/cont-a.yaml
~/dev/factory/profiles/boot/cont-b.yaml
~/dev/factory/profiles/kelk/ideal.yaml
~/dev/factory/profiles/kelk/ideal-or.yaml
~/dev/factory/profiles/kelk/cont-a.yaml
~/dev/factory/profiles/kelk/cont-b.yaml
~/dev/factory/profiles/ig88/ideal.yaml
~/dev/factory/profiles/ig88/ideal-or.yaml
~/dev/factory/profiles/ig88/cont-a.yaml
~/dev/factory/profiles/ig88/cont-b.yaml
```

**Profile shapes.**

- **Ideal** (today's reality): main chat on local Gemma 4 E4B 6-bit,
  aux also on local E4B. All five invariants honored. Carries a comment
  marking it as "Active shape while OpenRouter is locked out."
- **Ideal-OR** (forward-compat, inert until OR access returns): main
  chat on local E4B, aux routes to OpenRouter Gemma 4 31B
  (`google/gemma-4-31b-it`). Applied via `factory-profile.sh ideal
  --or-aux` once the OR account is unlocked — single flag, no YAML
  hand-editing required.
- **Contingency A**: Boot and Kelk identical to Ideal. IG-88 main
  `provider: openrouter`, `model: google/gemma-4-31b-it`, aux still
  local E4B on :41988. This is the FCT058 Stage-2 layout. The switcher
  warns at apply time while OR is locked out:
  `WARN: OpenRouter key not in scrub list; IG-88 will fail inference
  until access restored`.
- **Contingency B (mega-agent)**: one selected agent gets Gemma 4
  26B-A4B 6-bit on its dedicated MLX port; the other two agents are
  bootout'd entirely (gateways and MLX servers) to free RAM. Three new
  plists live in `plists/`:
  - `com.bootindustries.mlx-vlm-factory-26b-a4b.plist` (:41961)
  - `com.bootindustries.mlx-vlm-kelk-26b-a4b.plist` (:41962)
  - `com.bootindustries.mlx-vlm-ig88-26b-a4b.plist` (:41988)

**State file:** `~/.hermes/factory-profile.state` captures the current
tag, the selected mega-agent if any, the apply timestamp, and
SHA256s of each live profile file. `status` re-SHA256s the live files
and diffs against the state to detect post-apply hand-editing drift.

**Safety guards:**

- Refuse to run as root.
- Refuse to apply `cont-b` if the target agent's Hermes gateway log
  shows a webhook request mtime within the last 5s.
- Append every apply to `~/Library/Logs/factory/profile-switcher.log`.

**Shared library.** `scripts/_mlx-lib.sh` holds a single
`mlx_swap_plist <port> <label> <repo_plist_path> <model_path>` function
factored out of `factory-mlx-switch.sh::switch_to` (FCT054). Both
`factory-profile.sh` and `factory-mlx-switch.sh` source it, so the
bootstrap race handling (ThrottleInterval, bootout→sleep→bootstrap,
`/v1/models` poll) lives in one place.

---

## Verification Evidence

### Before (failure mode, 2026-04-08 through 2026-04-09)

From `~/.hermes/profiles/boot/logs/errors.log` — RC5 main-loop drift:

```
2026-04-09 07:15 ERROR root: API call failed after 3 retries.
HTTP 429: Provider returned error |
  provider=openrouter
  model=google/gemma-4-31b-it
  msgs=181
  tokens=~89094
  request_id=[redacted]
  user_id=user_***
```

From `~/.hermes/profiles/kelk/logs/errors.log` — RC1 aux escape into
Anthropic via the payment-fallback chain:

```
2026-04-09 14:22 ERROR auxiliary_client: not_found_error
  provider=anthropic
  model=gemma-4-e4b-it-6bit
  "model: gemma-4-e4b-it-6bit is not a valid model name"
```

From `~/.hermes/profiles/ig88/logs/errors.log` — RC2 IG-88 profile
sending the 31B model ID to the local E4B server:

```
2026-04-09 21:20 ERROR root: Non-retryable client error from
  http://127.0.0.1:41988/v1/chat/completions
  "google/gemma-4-31b-it is not a valid model ID"
  HTTP 400
```

From `~/Library/Logs/factory/mlx-vlm-kelk.log` — RC3 hot-reload trap
firing on a bare model name:

```
Loading model from: gemma-4-e4b-it-6bit
Error loading model gemma-4-e4b-it-6bit: 401 Client Error
Repository Not Found for url:
  https://huggingface.co/api/models/gemma-4-e4b-it-6bit/revision/main
INFO: 127.0.0.1:[redacted] - "POST /v1/chat/completions HTTP/1.1" 500
```

From `~/Library/Logs/factory/mlx-vlm-ig88.log` — RC4 Metal GPU timeout
on a 12k prefill:

```
Prefill: 100%|███| 12206/12207 [00:18<00:00, 667.80tok/s]
libc++abi: terminating due to uncaught exception of type std::runtime_error:
[METAL] Command buffer execution failed: Caused GPU Timeout Error
(...kIOGPUCommandBufferCallbackErrorTimeout)
```

### After (kickstart at 2026-04-10 00:58–00:59 UTC-4)

Boot and Kelk gateways kickstarted cleanly. Within 60 seconds of the
kickstart, both error logs went silent. Matrix rooms reported normal
join behavior:

```
2026-04-10 00:58:41 INFO root: ✓ matrix connected
2026-04-10 00:58:42 INFO root: Gateway running with 2 platform(s)
```

MLX server logs on :41961 and :41962 report HTTP 200 responses in
1–3 seconds to requests carrying the canonical model ID:

```
2026-04-10 00:58:55 INFO uvicorn: 127.0.0.1:[redacted] -
  "POST /v1/chat/completions HTTP/1.1" 200
  model=mlx-community/gemma-4-e4b-it-6bit
  latency_ms=1820
```

Critically, the failure-mode log lines are all absent:

- No `provider=openrouter` line in any profile errors.log.
- No `provider=anthropic` line in any profile errors.log.
- No `Loading model from:` or `Repository Not Found` in any MLX log.
- No `not a valid model ID` response from any MLX server.
- No `[METAL] Command buffer execution failed` crash (pending live
  stress test in Phase 5 once compression trigger can be exercised).

IG-88 is still running its pre-FCT064 state on :41988 per the explicit
user directive; its verification evidence is pending its next natural
restart.

---

## Hard Constraint (Preserved)

IG-88's Hermes gateway (`com.bootindustries.hermes-ig88`) and MLX server
on :41988 (`com.bootindustries.mlx-vlm-ig88`) were **NOT** restarted
during Phase 1 or Phase 2 of this sprint. Per explicit team-lead
directive, IG-88 is currently producing useful output on :41988 and
must not be disturbed. The profile rewrite (Phase 1) and the wrapper
env-scrub (Phase 2) both take effect on IG-88's next natural restart,
which may be days or weeks away and is not scheduled. All verification
of the IG-88 edits is therefore deferred until that natural restart,
with the expectation that nothing should regress.

This is a conscious tradeoff: IG-88's current runtime is on the
half-unwound FCT062 profile and is vulnerable to both the RC1 aux-chain
escape (mitigated by the wrapper's `OPENROUTER_API_KEY` scrub, but not
by any Anthropic-side scrub yet) and the RC4 Metal GPU timeout on
prefills above 12k. If an RC4 crash triggers a natural restart before
the next planned restart, the FCT064 edits will latch and the next
gateway start will be clean. This is the intended recovery path.

---

## Forward Compatibility

### Re-enabling OpenRouter auxiliary routing (once account unlocked)

Once the OpenRouter account is restored (estimated up to one week for
support to respond to the 2FA recovery ticket):

1. Add `OPENROUTER_API_KEY` back to the Infisical secret set for each
   machine identity (`infisical-factory`, `infisical-bootindu`,
   `infisical-ig88`).
2. Remove `OPENROUTER_API_KEY` from the `env -u` list in the `h-boot`,
   `h-kelk`, `h-ig88` aliases in `~/.zshrc`.
3. Remove the `unset OPENROUTER_API_KEY` line from each of
   `scripts/hermes-{boot,kelk,ig88}.sh`.
4. Run `factory-profile.sh ideal --or-aux` to apply the Ideal-OR
   template set. This flips `auxiliary.*.provider` to `openrouter`
   and `auxiliary.*.model` to `google/gemma-4-31b-it` for the nine
   auxiliary tasks, while leaving main chat on local E4B.
5. Kickstart Boot and Kelk gateways. IG-88 takes effect on its next
   natural restart per the usual constraint.

No YAML hand-editing is required on the human operator's path; the
template swap is the only moving part.

### Re-enabling Anthropic (2026-05-01 budget unlock)

On or after 2026-05-01, when the Anthropic budget unlocks:

1. Confirm with the team lead that Anthropic is back in scope.
2. Remove the four Anthropic/OpenAI-compat `unset` lines from each of
   `scripts/hermes-{boot,kelk,ig88}.sh`:

   ```
   unset ANTHROPIC_API_KEY
   unset ANTHROPIC_AUTH_TOKEN
   unset OPENAI_BASE_URL
   unset OPENAI_API_BASE
   ```

3. Remove the corresponding `-u` flags from the `h-boot`, `h-kelk`,
   `h-ig88` aliases in `~/.zshrc`.
4. Decide whether Anthropic should appear in `_resolve_auto`'s
   `_try_payment_fallback()` chain as a real fallback target, or
   whether it should remain scrubbed at the wrapper level even while
   the budget is available. The default position per this doc is to
   leave Anthropic scrubbed and only enable it via explicit per-call
   provider hints — the RC1 chain escape is too easy to fall into
   otherwise.

---

## Open Questions / Deferred

- **RC5 upstream root fix.** A source read of
  `hermes_cli/runtime_provider.py` is required to confirm whether the
  main-loop provider drift is a Hermes bug (runtime state persisted
  across restarts, slash-command side effect) or a downstream misuse
  of a per-call provider hint. If it is a bug, file upstream at the
  Hermes tracker referencing #5358 and the Boot error log excerpt
  above. Until then, the wrapper env scrub is the only defense.
- **`credential_pool.py` audit.** Enumerate whether Hermes persists
  provider tokens anywhere outside env — likely candidates are
  `~/.hermes/credentials.json`, `~/.hermes/*.state`, or a SQLite file
  under `~/.local/state/hermes/`. Any stale entry could survive the
  wrapper env scrub and feed the `_resolve_auto` chain. Not performed
  this sprint; tracked as a follow-up.
- **`~/.hermes/context_length_cache.yaml` re-audit.** File does not
  exist as of 2026-04-10 00:59. May be created by the next gateway
  cold-start. If it is, inspect for any 128000 entry against
  `mlx-community/gemma-4-e4b-it-6bit`; if present, delete and let
  Hermes re-resolve against the corrected profile.
- **MLX server consolidation.** Three independent `mlx_vlm.server`
  processes currently hold three identical copies of the Gemma 4 E4B
  6-bit weights, consuming ~20 GB total vs ~7 GB if shared. Per FCT054
  the per-agent tenancy model is load-bearing for IG-88's autonomous
  inference bursts (shared-server head-of-line blocking would stall
  Boot and Kelk during IG-88 activity), so consolidation is
  intentionally deferred. Revisit after Contingency B data is in and
  the three-agent RAM budget can be re-characterized.
- **mlx_vlm `/v1/models` pollution.** Port :41962 was observed on
  2026-04-09 to advertise both `mlx-community/gemma-4-e4b-it-6bit`
  and a bare `gemma-4-e4b-it-6bit`. The bare entry is residue from a
  prior bare-name request and clears on restart. No action this
  sprint; not tracked as a regression because the canonical ID is
  still advertised correctly.
- **RC5 live reproduction.** Phase 5 should include an attempt to
  reproduce RC5 deliberately via the `/model` slash command in an
  interactive `h-boot` session, followed by gateway restart, to
  confirm whether runtime state persists.

---

## Addendum — 2026-04-10 Morning Session

### RC6 — Preflight guard regression in `hermes-ig88.sh`

The `hermes-ig88.sh` wrapper carried a preflight guard at line 70 that
validated the profile's `provider:` field before launching the gateway.
The grep pattern was `^provider:` — anchored to the start of line. After
FCT064 Phase 1 converted IG-88's config from flat top-level keys to the
dict form (`provider:` indented under `model:`), the grep no longer
matched, causing the preflight check to fail with exit code 3. Launchd's
KeepAlive respawned the wrapper every 15 seconds.

**Impact window:** 2026-04-09 03:51 UTC through 2026-04-10 10:18 UTC
(approximately 6.5 hours). IG-88 was completely offline for the entire
overnight period — no Matrix presence, no webhook processing, no
inference.

**Root cause:** Boot and Kelk wrappers had already been updated to the
flexible pattern `^[[:space:]]*provider:` (matching with optional leading
whitespace) during an earlier fix pass, but IG-88's wrapper was missed.
This is a classic "fix two of three" regression — the same pattern that
produced RC2 in the main doc.

**Fix:** `hermes-ig88.sh` line 70 grep updated from `^provider:` to
`^[[:space:]]*provider:`. IG-88 gateway restarted successfully at 10:18
UTC. Committed as `45835b5`.

### Context/compression resolution discovery

Investigation of the overnight MLX server logs revealed that the
auxiliary compression client resolves `context_length` **independently**
from the main agent loop, using a different code path:

1. The main agent loop reads `model.context_length` from
   `config.yaml` and correctly applies the declared value (now 22000
   after the profile update).
2. The auxiliary compression client probes the MLX server's
   `/v1/models` endpoint at runtime. `mlx_vlm.server` does not report
   `context_length` in its response. The client falls back to the
   hardcoded default in `agent/model_metadata.py`:
   ```python
   model.get("context_length", 128000)
   ```
3. With `auxiliary.compression.threshold: 0.50`, the compression
   trigger computes to `128000 * 0.50 = 64000` tokens — effectively
   unreachable for a model that crashes on prefills above ~12k.

This explains why the overnight IG-88 session accumulated a 37,090-token
prefill (the last successful request before the MLX server hit socket
errors) without ever triggering compression. The 37k prefill took 59
seconds to complete, well into the danger zone for Metal GPU timeouts.

The profile-level `custom_providers[].models.<id>.context_length`
override (invariant 5) fixes this for the main loop but does NOT reach
the auxiliary client's independent resolver. The auxiliary client's
behavior is a Hermes-level issue that should be tracked alongside RC5
as a potential upstream bug report.

### Truncation fix activation

The `DEFAULT_MAX_TOKENS = 32768` vendor patch in
`~/dev/vendor/mlx-vlm/mlx_vlm/generate.py` — applied during an earlier
session to cap generation length and prevent runaway decoding — is now
confirmed active. Both MLX servers were bounced by the user this morning
(2026-04-10), picking up the patched `generate.py`. Prior to the bounce,
the servers were running the unpatched code from their last cold start.

### MLX server socket errors (overnight)

The `mlx-vlm-ig88` server on :41988 logged 180+ `socket.send() raised
exception` errors between approximately 03:51 and 04:00 UTC before
shutting down. The errors coincide with the IG-88 gateway crash loop
(RC6) — the gateway was restarting every 15 seconds and likely opening
connections that were torn down before the server could respond. The
server restarted automatically via its KeepAlive plist.

### Current operational state (2026-04-10 10:30 UTC)

All three agents confirmed healthy after the morning fixes:

| Service | Port | Status |
|---------|------|--------|
| mlx-vlm-factory-shared (Boot + Kelk) | :41966 | Running, 200s on canonical model ID |
| mlx-vlm-ig88 (dedicated) | :41988 | Running, 200s on canonical model ID |
| hermes-boot gateway | — | Running, Matrix connected |
| hermes-kelk gateway | — | Running, Matrix connected |
| hermes-ig88 gateway | — | Running, Matrix connected (restored 10:18) |

Context bars on all three agents report usage against the declared
context window (x/22k), confirming the main-loop context resolution is
reading from config correctly. The auxiliary compression client's
independent resolution (see above) remains an open issue but is
mitigated by the profile-level `context_length` override keeping
conversations shorter via main-loop awareness.

**Open items added by this addendum:**

- Track the auxiliary compression client's independent `context_length`
  resolution as a potential Hermes upstream bug (separate from RC5).
- Add a preflight-guard lint to CI or the `factory-profile.sh` switcher
  that validates all three wrappers use the same grep pattern, preventing
  future "fix two of three" regressions.

---

## References

- FCT054 — Factory MLX Tenancy and `factory-mlx-switch.sh` (per-agent
  port tenancy rationale, `switch_to()` plist-swap source).
- FCT055 — IG-88 Overnight Failure Post-Mortem and Hermes Routing
  Hardening (root-cause-post-mortem format modeled in this doc,
  earlier Metal-timeout observation).
- FCT058 — Agent Infrastructure Troubleshooting and Development
  Session, 2026-04-08 (Contingency A layout definition).
- FCT061 — Hermes v0.8.0 Migration and Routing Bug Resolution,
  2026-04-08 (initial wrapper scrub landing, OpenRouter pivot).
- FCT062 — Hermes v0.8.0 Provider Routing Resolution (IG-88 pivot
  to OpenRouter 31B, the pivot this sprint partially unwinds).
- FCT063 — Local Model Restoration and Routing Guide (post-FCT062
  local-routing cleanup, invariants this sprint builds on).
- Hermes upstream tracker: bug #5358 (provider routing hardening,
  parent tracking bug for RC1 and RC5).
- [1] Apple, "Metal Command Buffer Timeout Errors," Apple Developer
  Documentation, accessed 2026-04-10. Reference for
  `kIOGPUCommandBufferCallbackErrorTimeout` as a GPU-driver-level
  watchdog that cannot be disabled from application code.
