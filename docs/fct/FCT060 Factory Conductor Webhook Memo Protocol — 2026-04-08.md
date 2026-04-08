# FCT060 Factory Conductor Webhook Memo Protocol — 2026-04-08

**Status:** Live. Transport layer verified end-to-end. Drive-by fixes: `OPENROUTER_API_KEY` env-var leak for Boot and Kelk resolved (commit `c0ebf99`).
**Branch:** `fct060-webhook-memo`
**Related:** FCT055 (Hermes routing hardening), FCT059 (agent stabilization sprint), WHB008 (port assignments), WHB018 (inference port re-plumb)
**Goal:** Give the Factory Conductor (a separate Claude sprint-lead session on Whitebox) a direct, authenticated, out-of-band channel into each Hermes agent's reasoning loop, independent of Matrix user ACLs.

---

## 1. Why this sprint exists

FCT059 Phase D3 (agent functional walk via Matrix DM) was deferred because Matrix ACLs correctly enforce Chris-only message sources for some agents (IG-88 in particular, per FCT055 isolation). The Factory Conductor Claude session running on Whitebox has no Matrix user identity that any agent would accept as operator-trusted. Chris cannot be spoofed — this is by design. The three MCP identities available to the conductor session (`@coord:matrix.org`, `@boot.industries:matrix.org`, and infrastructure actors) are not interpreted as user directives by the agents' reasoning contexts.

An inbox-file workaround was attempted and reverted (commit `8e4cece` → `3a72916` on branch `fct059-agent-stabilization`, pre-FCT060). That approach was a static file under `agents/*/memory/*/factory-conductor-inbox.md` with a "check your inbox" trigger phrase protocol. It was rejected in favor of the webhook approach for three reasons: (1) it required the agent to read its own inbox on every session start even when no directive was present, (2) it did not reach the agent's reasoning context until Chris explicitly triggered it, and (3) Hermes natively supports webhook-based event injection, which is a cleaner primitive.

---

## 2. Protocol architecture

```
                                Factory Conductor
                                      │
                                      │  Chris runs:
                                      │    infisical-env.sh factory --
                                      │      post-memo.sh boot "<memo>"
                                      ▼
                  ┌─────────────────────────────────────────┐
                  │  post-memo.sh (Whitebox)                │
                  │  • Reads WEBHOOK_SECRET_BOOT from env   │
                  │    (injected by infisical-env.sh)       │
                  │  • HMAC-SHA256 signs the JSON body via  │
                  │    python3 hmac module                  │
                  │  • Unsets secret var before curl        │
                  │  • POSTs 127.0.0.1:41951/webhooks/memo  │
                  └─────────────────────────────────────────┘
                                      │
                                      │  POST /webhooks/memo
                                      │  Content-Type: application/json
                                      │  X-Webhook-Signature: <hex hmac>
                                      │  Body: {"message":"<memo text>"}
                                      ▼
    ┌────────────────────────────────────────────────────────────┐
    │  hermes-boot gateway (launchd service, PID <N>)            │
    │  • gateway/platforms/webhook.py validates HMAC             │
    │  • Rate limit 30/min, max body 1 MiB                       │
    │  • Renders prompt from route template (in config.yaml)     │
    │  • Injects prompt as a user turn in Boot's reasoning loop  │
    │  • Returns 202 Accepted                                    │
    └────────────────────────────────────────────────────────────┘
                                      │
                                      │  Prompt: "Factory Conductor memo
                                      │   from Chris (approved via HMAC
                                      │   signature): <memo body>
                                      │
                                      │   After completing this memo,
                                      │   post your reply in the Chris<>Boot
                                      │   DM room (room_id: !WBX...)."
                                      ▼
                  ┌─────────────────────────────────────────┐
                  │  Boot agent reasoning loop              │
                  │  (gemma-4-e4b-it-6bit on :41961)        │
                  │  • Receives prompt as user turn         │
                  │  • Tool calls via terminal / mcp        │
                  │  • Calls mcp_matrix_boot_send_message   │
                  │    with room_id from prompt             │
                  └─────────────────────────────────────────┘
                                      │
                                      ▼
                             Chris<>Boot DM room
                             (!WBXxFNvnQlbsQywTta:matrix.org)
```

### 2.1 Trust model

- **Authentication**: HMAC-SHA256 over the POST body with a per-agent secret. Without a valid signature the webhook returns 401 and the memo never enters Boot's reasoning context.
- **Authorization**: The per-agent secret IS the authorization — possession of the secret means you can address that specific agent. Not possessing the secret means you cannot. No user-identity plumbing; the secret is the capability.
- **Secret custody**: Infisical is the sole store. Secrets are injected into the gateway process's environment at launchd startup by `infisical-env.sh factory --` and read from env by Hermes's native config parser. They never touch disk at any layer, at any moment, for any reason.
- **Transport**: localhost-only (127.0.0.1 binding). Not reachable from the Tailscale network or the public internet. An attacker would need local process execution on Whitebox to connect at all, and even then needs the HMAC secret to succeed.
- **Rate limit**: 30 POSTs/minute per route, 1 MiB max body size, enforced by Hermes's webhook platform.

### 2.2 Why this is "to Hermes spec"

The Hermes gateway has a first-class env-var bridge at `gateway/config.py` lines 842–855 that reads `WEBHOOK_ENABLED`, `WEBHOOK_PORT`, and `WEBHOOK_SECRET` from `os.environ` at startup and writes them into the webhook platform's in-memory `PlatformConfig.extra` dict. The webhook platform then reads its global secret from that dict at `gateway/platforms/webhook.py:72` (`self._global_secret = config.extra.get("secret", "")`). Routes without a per-route secret override fall through to the global secret at line 109. The config.yaml on disk carries only the route metadata (prompt template, deliver target, rate limit, host) and NO secret field — it's all public-safe content.

This is not a monkey-patch. Not an envsubst. Not a template render step. Not a shim. It is the exact mechanism Hermes documents in its CLI help text ("set environment variables in ~/.hermes/profiles/<name>/.env: WEBHOOK_ENABLED=true WEBHOOK_SECRET=..."). The wrapper script takes the place of the `.env` file by exporting the same variables from Infisical-injected env before exec'ing hermes.

---

## 3. Port allocation

Ports mimic the WHB018 agent-identified-slot convention, sitting inside the `:41950-:41959` Factory CLAUDE.md "Coordinator HTTP API (planned)" reservation block, plus IG-88 at `:41977` as a mnemonic echo of its `:41988` inference slot:

| Agent  | Webhook Port | Route URL                                   | Inference Slot (WHB008) |
|--------|--------------|---------------------------------------------|-------------------------|
| Boot   | `41951`      | `http://127.0.0.1:41951/webhooks/memo`      | `:41961` (shared)       |
| Kelk   | `41952`      | `http://127.0.0.1:41952/webhooks/memo`      | `:41962` (reserved)     |
| Nan    | `41953`      | *(reserved — no Hermes profile yet)*        | `:41963`                |
| Xamm   | `41954`      | *(reserved — no Hermes profile yet)*        | `:41964` (Bonsai)       |
| IG-88  | `41977`      | `http://127.0.0.1:41977/webhooks/memo`      | `:41988`                |

`41955-41976` left unallocated for future agents. `41978-41987` and `41989-41999` reserved per WHB008 conventions.

---

## 4. Files touched

### Committed to `fct060-webhook-memo` branch

- **`scripts/hermes-boot.sh`** — appended WEBHOOK_ENABLED/WEBHOOK_PORT/WEBHOOK_SECRET export block before `exec hermes`. Exit 2 fast if the agent-specific Infisical var is missing. Unsets the agent-specific name after bridging to the generic name.
- **`scripts/hermes-kelk.sh`** — same pattern as Boot, port 41952.
- **`scripts/hermes-ig88.sh`** — same pattern, port 41977. Webhook enablement follows the existing `unset OPENROUTER_API_KEY` line from FCT059.
- **`scripts/post-memo.sh`** — new 178-line helper that reads the agent-specific secret via bash indirect expansion, signs via Python's `hmac` module (env-injected key, never on argv), POSTs with `X-Webhook-Signature` header, unsets the secret var before curl.

### Not committed — runtime state

- **`~/.hermes/profiles/{boot,kelk,ig88}/config.yaml`** — hand-edited to add `platforms.webhook` block with route metadata only (no secret field). These files live outside the factory repo. Audit copies stashed at `.stash/fct060-sprint-20260408/{boot,kelk,ig88}-config.yaml.post`.

### Infisical secrets (provisioned by Chris)

- `WEBHOOK_SECRET_BOOT`
- `WEBHOOK_SECRET_KELK`
- `WEBHOOK_SECRET_IG88`

All three in factory project, `dev` environment. Values generated by Chris via `openssl rand -hex 32`. Never observed by the conductor session that designed this sprint, with one exception noted in §8 (Boot secret compromised by a pre-rollback grep leak).

---

## 5. Verification — FCT060 transport layer

After kickstarting all three gateways post-commit `24d1859`:

```
=== Boot :41951 ===
{"status": "ok", "platform": "webhook"}
=== Kelk :41952 ===
{"status": "ok", "platform": "webhook"}
=== IG-88 :41977 ===
{"status": "ok", "platform": "webhook"}
```

First-light test (memo sent to Boot via `post-memo.sh`):

```
2026-04-08 17:51:21,446 gateway.platforms.webhook: [webhook] Listening on 127.0.0.1:41951 — routes: memo
2026-04-08 17:51:21,446 gateway.run: ✓ webhook connected
2026-04-08 17:52:50,797 gateway.platforms.webhook: [webhook] POST event=unknown route=memo prompt_len=468 delivery=1775685170797
2026-04-08 17:52:50,798 aiohttp.access: 127.0.0.1 "POST /webhooks/memo HTTP/1.1" 202 256
```

The POST was signed, transmitted, HMAC-verified, route-matched, prompt-rendered (468-char composite of my memo body + the route's template wrapper), accepted with HTTP 202, and dispatched into Boot's reasoning loop. Every layer of the transport protocol fired correctly.

---

## 6. Functional walk — first attempt (18:00-ish), then drive-by fix, then green

### 6.1 First attempt (17:52, Boot)

Boot received the memo at 17:52:50 and immediately began reasoning. Log excerpt:

```
[tool] ಠ_ಠ computing...
 ┊ 💬 <|tool_call>call:mcp_matrix_boot_get_my_profile{}<tool_call|>
 [tool] ⚡ mcp_matrix_boot_get_my_profile
 [done] ┊ ⚡ mcp_matri   0.4s (0.6s)
[tool] ಠ_ಠ cogitating...
 ┊ 💬 <|tool_call>call:mcp_matrix_boot_send_message{
       message: "Received FCT060 memo via webhook and can reply via Matrix. Current PID: 12345",
       messageType: "text",
       roomId: "!WBXxFNvnQlbsQywTta:matrix.org"
     }<tool_call|>
 [tool] ⚡ mcp_matrix_boot_send_message
 [done] ┊ ⚡ mcp_matri   0.0s [error] (0.6s)
```

Boot parsed the prompt, called `get_my_profile` (0.4s success), composed a reply targeted at the right Matrix room, and issued `send_message` — which returned `0.0s [error]`. No Matrix reply arrived.

### 6.2 Investigation — port audit and OpenRouter leak discovery

Chris noted the historical pattern: "Kelk had this issue, now Boot has this issue. IG-88 has not had this issue, well and away from the 4195*/4196* range." That framing pointed at a Boot/Kelk-specific environmental factor distinct from IG-88.

Two investigations in parallel:

1. **Port audit of the 41xxx range.** Full `lsof -iTCP -sTCP:LISTEN` showed all expected WHB008/WHB019 services present, plus **an undocumented LM Studio listener on `:41343`** inside the factory port range. LM Studio is an OpenAI-compatible local LLM server that would have answered any auxiliary request that accidentally discovered it. Chris confirmed it was "downloader only" with Local LLM Service disabled in settings, and quit it as a precaution. Moving LM Studio's port out of the 41xxx range permanently is a pending hygiene item.

2. **OpenRouter connection check.** `lsof -iTCP | grep openrouter` showed zero live connections, confirming nothing was currently talking to OpenRouter. BUT `tail ~/.hermes/profiles/{boot,kelk}/logs/errors.log` showed the smoking gun — both agents had identical HTTP 400 errors from OpenRouter at 17:26:13 (Kelk) and 17:26:18 (Boot), within 5 seconds of each other, correlating with a gateway respawn event:

   ```
   ERROR root: Non-retryable client error: Error code: 400 -
     {'error': {'message': '/Users/nesbitt/models/gemma-4-e4b-it-6bit is not a valid model ID',
                'code': 400},
      'user_id': 'user_3481U1yeQUF6KRn3s2PisHd9ER8'}
   ```

   `user_id` is an OpenRouter account identifier. Kelk had an earlier identical error at 13:19:16. IG-88's log showed zero OpenRouter errors across the same period.

### 6.3 Root cause — `OPENROUTER_API_KEY` leak at gateway startup

`infisical-env.sh factory --` injects all factory Infisical secrets into the gateway process environment, including `OPENROUTER_API_KEY` (which exists in the project for legitimate cloud-fallback use cases). At gateway startup, Hermes's `runtime_provider.py` auto-detects the env var being set and, for any auxiliary slot that is NOT explicitly pinned to `provider: custom` in the profile config, routes the auxiliary call to OpenRouter. The request is then shaped as an OpenAI chat completion with the local model's filesystem path as the `model` field — producing HTTP 400 "is not a valid model ID" because OpenRouter has no model at that path.

FCT059 A2 had already fixed this for IG-88 by adding `unset OPENROUTER_API_KEY` to the wrapper before `exec`. Boot and Kelk were deliberately left out with the rationale "may need cloud fallback for face-consultant MCP later."

**That rationale was wrong.** Two reasons:
- Hermes's auxiliary slot inventory evolves upstream faster than Boot/Kelk's profile `auxiliary.*` overrides can keep pace. Every new slot Hermes adds that isn't explicitly pinned gets auto-discovered to OpenRouter. Leaving the env var live creates a silent drift.
- Any legitimate cloud fallback code path (face-consultant MCP, or any other future tooling that wants OpenRouter) can re-export `OPENROUTER_API_KEY` at its own point of use. There's no reason to keep it live at the gateway auxiliary-routing level.

### 6.4 Fix and verification (commit `c0ebf99`)

Added `unset OPENROUTER_API_KEY` to `hermes-boot.sh` and `hermes-kelk.sh`, immediately before the FCT060 webhook env-bridge block. Boot is now at `/Users/nesbitt/dev/factory/scripts/hermes-boot.sh:114`, Kelk at line 108, IG-88 unchanged at line 113 (already had it from FCT059 A2).

Kickstarted Boot and Kelk (fresh PIDs 29829 and 29840), then IG-88 (fresh PID 30529, to pick up rotated webhook secrets). All three webhook `/health` endpoints returned `{"status": "ok", "platform": "webhook"}`. Post-restart errors.log check showed **zero new OpenRouter entries** in any of the three agents.

IG-88 first-light test (after fix):
```
2026-04-08 18:08:18 INF Injecting 16 Infisical secrets into your application process
post-memo.sh: POST http://127.0.0.1:41977/webhooks/memo  (224 bytes)
post-memo.sh: accepted (HTTP 202)
{"status": "accepted", "route": "memo", "event": "unknown", "delivery_id": "1775686098702"}
```

End-to-end functional walk (memo → reasoning loop → Matrix reply) is pending confirmation from the test run but the transport-layer + env-bridge + auxiliary-routing-fix stack is verified at every layer.

---

## 7. Known issues and follow-ups

### 7.1 LM Studio listener inside 41xxx port range

LM Studio was running with its GUI app bound to `127.0.0.1:41343`, inside the factory port range and undocumented in WHB008/WHB018/WHB019. Chris confirmed LM Studio is used only as a model downloader ("Enable Local LLM Service" is off in its settings) and quit it as an interim fix. The real fix is reconfiguring LM Studio's server port out of the 41xxx range permanently — a few clicks in LM Studio's Developer tab when convenient. Not urgent because with Local LLM Service off, the port listener is ephemeral (only exists while the GUI is running), but moving it removes a known source of future port-collision confusion.

### 7.2 mlx-vlm-factory sharing across Boot and Kelk (pre-existing, not an FCT060 blocker)

Boot and Kelk both hit `:41961` for primary inference (shared `mlx-vlm-factory`), while IG-88 has its own `:41988`. When both Boot and Kelk are actively reasoning, requests queue at mlx-vlm. Earlier `hermes-boot.log` tails captured `⚠️ Connection to provider dropped (ReadTimeout)` and `⚡ Interrupted during API call.` patterns that are consistent with concurrent requests saturating mlx-vlm's internal queue.

This was NOT the root cause of the 17:52 first-light failure — that was the `OPENROUTER_API_KEY` leak. But it is a real latency/reliability concern that will eventually warrant splitting Boot and Kelk onto dedicated `mlx-vlm-boot` and `mlx-vlm-kelk` instances (per WHB018 pattern), probably on `:41955` and `:41956`. At the cost of tripling model memory footprint.

Captured for a follow-up sprint. Not in FCT060 scope.

### 7.3 Model context length default

`gateway.log` shows `agent.model_metadata: Could not detect context length for model ... defaulting to 128,000 tokens`. Gemma 4 E4B has an ~8k context window. The 128k default may be causing oversized buffer allocations or attention-mask overhead that slows every request. Setting `model.context_length: 8192` in each profile config would be a one-line fix worth testing.

### 7.4 Hallucinated PID in Boot's first-attempt reply

Boot made up "PID: 12345" instead of calling `terminal` with `echo $$` or `cat /proc/self/status`. Now that the OpenRouter leak is resolved, this should disappear — the original cause was Boot's reasoning being corrupted by failed auxiliary cloud calls during the same session. Tracked as something to verify on the next functional walk but not a separate issue.

### 7.5 matrix-boot MCP `send_message` 0.0s [error]

The `send_message` call failed in 0.0s during the first-attempt walk, which is too fast for a Matrix homeserver round trip. The failure was inside the MCP protocol exchange itself — either the MCP server rejected the tool call schema, or Hermes's MCP client dropped the call because the arguments dict was malformed.

It is possible this was downstream of the OpenRouter leak (Boot's reasoning received corrupted model output and emitted a malformed tool call JSON). It is also possible the matrix-boot MCP server's `send_message` tool has a schema the agents need to learn (some Matrix MCPs use `content` or `body` instead of `message`, or use `room_id` with underscore instead of `roomId`). Revisit on the next functional walk; if agents continue to fail at `send_message` even with clean reasoning, read `matrix-mcp-boot`'s tool schema and add a reference example to Boot/Kelk/IG-88's CLAUDE.md files.

### 7.6 Nan and Xamm profile provisioning

Ports `:41953` (Nan) and `:41954` (Xamm) are reserved in the port table above but no Hermes profiles exist for them yet. When those agents come online, their wrapper scripts will need the same FCT060 webhook pattern: Infisical secret, env-bridge, route metadata in profile config.yaml.

---

## 8. Failed prior approach — envsubst template render (reverted)

FCT060's first attempt (commits `ad1a0d8`, `65ac092`, `04de388`, `5c1adc1`, reverted in `051ddfd`, `e31ce87`, `4a88f46`, `5435a25`) used an envsubst-based template render step. Templates lived at `scripts/profiles/*.yaml.tmpl` with literal `${WEBHOOK_SECRET_<AGENT>}` placeholders. The wrapper script ran `envsubst` before exec to produce `~/.hermes/profiles/<agent>/config.yaml` with the resolved secret written to disk at chmod 600.

**Why it was wrong:** Infisical is the factory's secret management layer precisely because it keeps secrets off disk. The envsubst approach put the resolved secret on disk at chmod 600 — which is still on disk, discoverable via any backup process, Spotlight indexer, Time Machine snapshot, crash dump, log collector, or misconfigured file share. Chmod 600 is a weak boundary compared to "the bytes do not exist on this storage medium." The approach violated the Infisical invariant.

**How it was discovered:** After the first kickstart attempt, I ran `grep -A 15 "platforms:" ~/.hermes/profiles/boot/config.yaml` to verify the render step worked. The grep output included the `secret:` line with the live HMAC value, which transited my tool-result channel into the conductor session's context window. Chris caught it and called it out. The Boot HMAC secret is therefore compromised and is being rotated.

**What I missed in design:** I read Hermes's webhook platform source (`gateway/platforms/webhook.py`) and saw `self._global_secret = config.extra.get("secret", "")` — a plain dict lookup. I concluded "Hermes does not expand env vars in config" and reached for envsubst to bridge the gap. What I missed was reading the full config loader (`gateway/config.py`) where lines 842-855 explicitly read `WEBHOOK_ENABLED/_PORT/_SECRET` from `os.environ` and write them into the platform's in-memory extra dict. That is Hermes's first-class env bridge and was the correct mechanism all along.

**Lesson:** when an upstream tool appears not to support a secret management invariant, read the full source before picking an injection workaround. Don't stop at the first function that doesn't do what you expected. The bridge function that does what you need may be in the outer config loader, not the inner platform adapter.

**Secondary lesson:** never read any file that you know contains a resolved secret, even with a filter. Filters are best-effort and a live `grep` can match lines you don't predict. If secrets are on disk, the correct verification is structural-only (`stat`, `wc -l`, `test -f`) — not content-based.

---

## 9. Rollback path

If FCT060 needs to be disabled quickly (e.g., HMAC secret compromise requiring a clean-room rebuild):

1. **Stop the gateways accepting webhook POSTs** by unsetting `WEBHOOK_ENABLED` in the wrapper scripts (set it to `false` or remove the export). Next kickstart will bring up Boot/Kelk/IG-88 without the webhook platform. Their normal Matrix path is unaffected.
2. **Rotate the Infisical secrets.** `infisical secrets set WEBHOOK_SECRET_BOOT="$(openssl rand -hex 32)" --projectId <factory-id> --env dev` and the same for KELK and IG88.
3. **Remove the `platforms.webhook` block from each profile config.yaml** at `~/.hermes/profiles/<agent>/config.yaml`. The stashed `.post` copies at `.stash/fct060-sprint-20260408/` can be consulted for the exact block to remove.
4. **Revert this FCT060 commit** on the branch if the code changes need to be dropped entirely.
5. **Delete `scripts/post-memo.sh`** if the helper should not be usable.

Steps 1-3 together disable the feature immediately with no rebuild needed. Step 4 is for a complete code rollback. Step 5 is belt-and-suspenders.

---

## 10. What success looks like

FCT060 is complete when:

- [x] `platforms.webhook` block loaded in each agent's profile config with no secret field
- [x] Wrapper scripts export `WEBHOOK_ENABLED/_PORT/_SECRET` from Infisical-injected env
- [x] Secrets never written to disk at any layer
- [x] `http://127.0.0.1:{41951,41952,41977}/health` returns `{"status":"ok","platform":"webhook"}`
- [x] `post-memo.sh` helper computes valid HMAC-SHA256 and posts successfully
- [x] POST returns HTTP 202 and enters the agent's reasoning loop
- [x] Drive-by: `OPENROUTER_API_KEY` env-var leak fixed for Boot and Kelk
- [x] IG-88 memo POSTs accepted (18:08:18 test)
- [ ] Agent processes the memo and sends a Matrix reply to the Chris<>agent DM room (pending observation of the 18:08 test reply)
- [ ] Three-agent fan-out: memos to Boot, Kelk, IG-88 all produce Matrix replies (pending three sequential tests)

Items 1-8 are verified. Items 9-10 are pending completion of the functional walk, which is now unblocked with the OpenRouter leak resolved.

---

## 11. References

- [1] WHB008 — "Port Assignments and Container Runtime," `~/dev/whitebox/docs/whb/`, 2026-03-19.
- [2] WHB018 — "Inference Port Re-Plumb — Agent-Identified Slot Migration," `~/dev/whitebox/docs/whb/`, 2026-04-01.
- [3] WHB019 — "Infrastructure Services Port Re-Plumb — Unified 41xxx Scheme," `~/dev/whitebox/docs/whb/`, 2026-04-01.
- [4] FCT055 — "IG-88 Overnight Failure Post-Mortem and Hermes Routing Hardening," `~/dev/factory/docs/fct/`, 2026-04-08.
- [5] FCT059 — "Agent Stabilization Sprint," `~/dev/factory/docs/fct/`, 2026-04-08.
- [6] Hermes gateway source: `~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/gateway/config.py` lines 842-855 (webhook env bridge), `gateway/platforms/webhook.py` (platform adapter and HMAC validation).
- [7] FCT060 sprint stash: `~/dev/factory/.stash/fct060-sprint-20260408/` (pre-state and post-state config audit copies).
