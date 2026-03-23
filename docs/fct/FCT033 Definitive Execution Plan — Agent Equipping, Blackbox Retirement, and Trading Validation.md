# FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation

**Date:** 2026-03-23
**Status:** Active
**Type:** Master Execution Plan
**Supersedes:** FCT029 §5 (Recovery Priorities), FCT029 §8 (Whitebox Migration Plan), FCT029 §11 (Open Decisions — Blackbox role)
**Incorporates:** FCT029, FCT030, FCT031, FCT032, IG88003-032, BKX122, WHB003-006
**Related:** BKX058, BKX065, BKX074, BKX078, BKX080, BKX119, BKX125, BKX126

---

## 1. Scope and Purpose

This document is the definitive execution plan for three converging workstreams:

1. **Agent equipping** — restoring IG-88 and Kelk to operational status, wiring IG-88's trading API keys, and beginning paper trading validation
2. **Blackbox retirement** — full consolidation of all Factory services onto Whitebox, including Secrets Manager setup, launchd plist creation, and migration of the remaining application layer
3. **Trading validation** — a revised 100-trade paper trading protocol incorporating all seven caveats from the FCT032 research consultant review

**Key decisions captured in this document:**
- Blackbox (RP5) is fully retired from the Factory topology — resolved from FCT029 §11
- RP5 hardware is repurposed as a dumb watchdog (bash cron, no LLM) — physically independent health monitor for Whitebox
- Expectancy replaces win rate as the primary trading validation metric
- E2EE cutover is sequenced after Blackbox retirement and a 7-day stability gate

**Inputs:** This plan was developed through parallel subagent exploration of FCT, BKX, WHB, IG88, and OLM documentation; Qdrant semantic search across projects-vault and research-vault; and a formal research consultant review (FCT032) that validated the infrastructure strategy and raised seven critical caveats on the trading architecture.

---

## 2. Current System State

**Ground truth as of 2026-03-23.**

### 2.1 Infrastructure Topology

| Host | Hardware | Tailscale IP | Role |
|------|----------|-------------|------|
| Cloudkicker | MacBook Pro M2 16GB | 100.86.68.16 | Dev machine, source of truth for all code |
| Whitebox | Mac Studio M1 Max 32GB | 100.88.222.111 | Primary inference, databases, infrastructure |
| Blackbox | Raspberry Pi 5 8GB | 100.87.53.109 | Remaining agent runtime — scheduled for full retirement |

### 2.2 Service Inventory

**Whitebox (operational)**

| Service | Port | Status | Notes |
|---------|------|--------|-------|
| Qdrant | 6333/6334 | LIVE | 22,811 points across two collections |
| FalkorDB | 6379 | LIVE | Colima Docker; migrated WHB006 |
| Graphiti MCP | 8444 | DOWN | Depends on MLX-LM :8081 which is not running |
| Pantalaimon | 8009 | LIVE | launchd; Olm DB migrated from Blackbox |
| Ollama | 11434 | LIVE | nomic-embed-text embeddings |
| MLX-LM :8080-8083 | 8080-8083 | DOWN | Validated but no launchd plists; manual start required |

**Blackbox (scheduled for retirement)**

| Service | Port | Status | Notes |
|---------|------|--------|-------|
| coordinator-rs | — | BROKEN | Sync fails every ~90s; token not in systemd env |
| matrix-mcp Boot | 8445 | LIVE | |
| matrix-mcp Coord | 8448 | LIVE | |
| Qdrant MCP proxy | 8446 | LIVE | Proxies Whitebox :6333 |
| Research MCP proxy | 8447 | LIVE | Proxies Whitebox :6333 |
| Portal Caddy | 41910 | LIVE | |
| GSD sidecar | 41911 | LIVE | |
| Auth sidecar | 41914 | LIVE | |

### 2.3 Agent Status

| Agent | Identity | Status | Blocker |
|-------|----------|--------|---------|
| @boot | @boot.industries:matrix.org | ACTIVE (degraded) | Coordinator sync failing |
| @ig88 | @ig88bot:matrix.org | OFFLINE | Pantalaimon token lost during FCT022 source sync |
| @kelk | @sir.kelk:matrix.org | OFFLINE | Same — token lost |
| @nan | — | NOT BUILT | LFM2.5 tool-call adapter needed (BKX080) |
| @xamm | — | NOT BUILT | Domain 50 defined; design not started |

### 2.4 Security Grade: A-

All 24 red-hat findings closed (FCT023). 5 portal security fixes on Cloudkicker source but not deployed to Blackbox production. Phase 3 (A- → A+) not started.

---

## 3. Agent Roster and Health

### 3.1 Active Agent Roster

| Agent | Role | Model | Trust | Status | To Bring Online |
|-------|------|-------|-------|--------|-----------------|
| @boot | Project manager, operations, delegation | Nanbeige4.1-3B (:8080) | L3 Operator | Active (degraded) | Fix coordinator sync |
| @ig88 | Autonomous trading, signal-to-decision pipeline | Qwen3.5-4B (:8081) | L2 Advisor | OFFLINE | Restore Pan token; wire Jupiter API key |
| @kelk | Contemplative soul, philosophical guidance | Qwen3-4B (:8081) | L3 Operator | OFFLINE | Restore Pan token |
| @nan | Meta-agent advisor, strategic review, observer-only | Qwen3.5-9B (:8083) | TBD | NOT BUILT | Matrix account; LFM2.5 tool-call adapter (BKX080) |
| @xamm | Practical secretary — appointments, correspondence, errands | TBD | TBD | NOT BUILT | Everything |

### 3.2 IG-88 Trading Sub-Agents

IG-88 internally runs a 5-agent consensus system. These are not Matrix agents — they are Claude Code subagents spawned per analysis cycle:

| Sub-Agent | Scope | Model Tier |
|-----------|-------|------------|
| Regime Detection | Macro conditions: BTC, funding, liquidations, ATR | Haiku (speed-critical, every 15 min) |
| Scanner | Token selection: volume, momentum, exclusion criteria | Haiku |
| Narrative | WHY price moves — COHERENT / NOISE / SUSPICIOUS | Sonnet (contextual judgment) |
| Exit Management | Open positions: HOLD / CLOSE / PARTIAL triggers | Haiku |
| Governor | Synthesis + Kill Zone sizing; final recommendation | Sonnet (synthesis + risk) |

### 3.3 Coordination Tax — Research Consultant Caveat

DeepMind research documents accuracy degradation past 4 agents [FCT032]. IG-88 has 5 — at the threshold. Multi-agent is "demanding, not inferior" but requires extremely narrow scope per agent and minimal coordination surface (shared data, not shared context).

**Collapse criteria — merge agents into skills on one agent when ANY of:**

1. An agent regularly passes its full output to another agent as context, rather than a structured summary
2. Governor approval rate drops below 60% (inter-agent noise exceeds signal)
3. A single agent's output is consistently overridden by another's reasoning
4. End-to-end cycle latency exceeds 4 minutes (cannot react to intrabar regime shifts)

**Most likely collapse candidates:**
- Narrative + Scanner → single token-evaluation skill (if conviction scores are consistently correlated r > 0.8)
- Regime + Exit → collapse Regime into an Exit skill (if Exit is re-running regime logic)

Monitor during Phase C validation via conversation log review at 25-trade milestones.

---

## 4. Blackbox Retirement — Migration Manifest

**Decision: Full retirement.** Rationale documented in FCT031 and validated by FCT032 research consultant. Compound failure math, Agent Orchestration Layer pattern, and "minimize coordination surface" finding all support colocation on one host.

### 4.1 Prerequisites (Tier 0)

| Item | Action |
|------|--------|
| Whitebox username decision | Choose `chrislyons` or `nesbitt`; all plist paths depend on this |
| MLX-LM servers started | Start all four manually; then create launchd plists (Section 6) |
| Graphiti verified | `curl http://100.88.222.111:8444/sse` after :8081 is running |
| BWS setup complete | Bitwarden Secrets Manager per Section 5 |
| Outstanding commits pushed | factory, matrix-mcp repos |

### 4.2 Migration Tiers (Dependency Order)

**Tier 1 — Stateless MCP Proxies**

| Service | Port | Method |
|---------|------|--------|
| Qdrant MCP | 8446 | Stop systemd on Blackbox; deploy launchd plist on Whitebox; update `~/.mcp.json` |
| Research MCP | 8447 | Same |

Gate: Qdrant search returns results via Whitebox endpoint.

**Tier 2 — Matrix MCP Servers**

| Service | Port | Method |
|---------|------|--------|
| matrix-mcp Boot | 8445 | Copy `~/.local/state/matrix-mcp/boot/` to Whitebox; deploy launchd plist |
| matrix-mcp Coord | 8448 | Same with coord state dir |

Gate: Test Matrix message round-trips via Whitebox instances.

**Tier 3 — Coordinator**

| Service | Method |
|---------|--------|
| coordinator-rs | `cargo build --release` on Whitebox; update `agent-config.yaml` (graphiti_url → localhost, default_device → whitebox); deploy launchd plist; 48h parallel operation |

Gate: All three agents respond via Whitebox coordinator. Approval flow validated.

**Tier 4 — Portal Stack**

| Service | Port | Method |
|---------|------|--------|
| Auth sidecar | 41914 | Copy `auth.py`; launchd plist with bws secret injection |
| GSD sidecar | 41911 | Copy `server.py` + `jobs.json`; launchd plist |
| Portal Caddy | 41910 | Install Caddy on Whitebox; update Caddyfile bind address to `100.88.222.111:41910`; `make sync` targeting Whitebox |

Gate: `curl http://100.88.222.111:41910/jobs.json` returns valid JSON. Auth works. Portal loads.

**Tier 5 — Decommission Blackbox**

1. Stop and disable all Blackbox systemd services
2. BKX119 cleanup: remove `/home/nesbitt/projects/ig88` monolith
3. Power down RP5
4. Retain powered-down for 30 days as cold standby
5. Update all CLAUDE.md files and topology docs

### 4.3 RP5 Watchdog Role

After retirement from Factory, RP5 is repurposed as a **dumb health watchdog** — no LLM, no agent, no Coordination Tax.

**Rationale (from research vault):**
- Skills-First decision: don't add agents where structured automation suffices
- Minimal Agent Surface pattern: health checking is deterministic
- RP5 draws ~5W idle — physically independent from the thing it monitors
- An agent on Whitebox monitoring Whitebox is useless when Whitebox dies

**Implementation:** ~50 lines of bash, cron-scheduled every 2 minutes:

1. Ping each Whitebox service (Qdrant, FalkorDB, Graphiti, Pantalaimon, MLX-LM :8080-8083, coordinator, Portal Caddy)
2. Check HTTP response codes / TCP connect timeouts
3. On 2 consecutive failures for any service: send Matrix message to operator's DM room via curl to Synapse API
4. Optional: push notification via ntfy.sh or Pushover

**No LLM required.** If alert volume creates a signal-to-noise problem that needs triage, layer on intelligence later. Start dumb.

---

## 5. Bitwarden Secrets Manager Setup

**Prerequisite for Phase 2c.** Without this, launchd plists on Whitebox have no secure mechanism for unattended credential injection.

### 5.1 Architecture

| Machine | Backend | Status |
|---------|---------|--------|
| Cloudkicker | `bw` CLI + macOS Keychain (`BW_SESSION`) | Complete (BKX121) — no change |
| Blackbox | age (`id_blackbox_navy`, no passphrase) | Working until retirement — no change |
| Whitebox | `bws` CLI + macOS Keychain (`BWS_ACCESS_TOKEN`) | **To be implemented** |

### 5.2 Setup Procedure

1. Verify Secrets Manager enabled for Boot Industries org at `vault.bitwarden.eu`
2. Create project `factory/agents` in Secrets Manager
3. Populate secrets from inventory (Section 5.3) — source values from Cloudkicker `bw get password <item-name>`
4. Create service account `whitebox-factory-agents` with read-only access to `factory/agents`
5. Store access token in Whitebox macOS Keychain: `security add-generic-password -s "bitwarden-secrets-manager" -a "whitebox-factory-agents" -w "<TOKEN>"`
6. Install `bws` CLI: `brew install bitwarden/tap/bws`
7. Write Whitebox variant of `mcp-env.sh` (retrieves `BWS_ACCESS_TOKEN` from Keychain, fetches secrets via `bws secret get <UUID>`)
8. Cold-boot validation: reboot Whitebox with no active session, confirm all launchd services start

### 5.3 Secrets Inventory

**Matrix Authentication**

| Secret | Consuming Service |
|--------|-------------------|
| `MATRIX_TOKEN_BOOT_PAN` | matrix-mcp Boot (:8445) |
| `MATRIX_TOKEN_IG88_PAN` | coordinator-rs |
| `MATRIX_TOKEN_KELK_PAN` | coordinator-rs |
| `MATRIX_TOKEN_COORD_PAN` | coordinator-rs |

**Infrastructure**

| Secret | Consuming Service |
|--------|-------------------|
| `GRAPHITI_AUTH_TOKEN` | Graphiti MCP, coordinator-rs |
| `QDRANT_API_KEY` | Qdrant MCP, Research MCP |
| `ANTHROPIC_API_KEY` | Graphiti entity extraction |
| `OPENROUTER_API_KEY` | coordinator-rs LLM failover |

**Portal**

| Secret | Consuming Service |
|--------|-------------------|
| `AUTH_SECRET` | Auth sidecar (:41914) |
| `AUTH_BCRYPT_HASH` | Auth sidecar (:41914) |

**Market Data (IG-88)**

| Secret | Consuming Service |
|--------|-------------------|
| `LUNARCRUSH_API_KEY` | IG-88 tooling |
| `JUPITER_API_KEY` | jupiter-mcp (added during Phase B) |

---

## 6. Whitebox Launchd Plists

### 6.1 Conventions

- **Naming:** `com.bootindustries.<service-name>.plist`
- **Location:** `~/Library/LaunchAgents/` (user-level — preserves Keychain access for `bws`)
- **Logs:** `~/Library/Logs/factory/<service-name>.log`
- **Restart:** `KeepAlive = true`, `ThrottleInterval = 10-15`
- **Secrets:** Services needing credentials use `mcp-env.sh` (bws variant) as `ProgramArguments` wrapper

### 6.2 Startup Order

| Order | Services | Dependencies |
|-------|----------|-------------|
| 1 | MLX-LM :8080-8083, Pantalaimon :8009, Ollama :11434, Qdrant :6333 | None (foundation tier) |
| 2 | Graphiti :8444, Qdrant MCP :8446, Research MCP :8447 | Qdrant, MLX-LM :8081, Ollama |
| 3 | matrix-mcp :8445/:8448, Auth :41914, GSD :41911 | Pantalaimon |
| 4 | coordinator-rs, Portal Caddy :41910 | Graphiti, matrix-mcp, Auth, GSD |

launchd does not enforce inter-plist ordering. Services use `KeepAlive` retry to handle startup races — Graphiti retries until :8081 is healthy; coordinator retries until Graphiti and matrix-mcp respond.

### 6.3 Plists Required (12 total)

| Plist | Service | Secrets |
|-------|---------|---------|
| `com.bootindustries.mlx-lm-8080` | Nanbeige4.1-3B (Boot/IG-88) | None |
| `com.bootindustries.mlx-lm-8081` | Qwen3.5-4B (Kelk/Expert/Graphiti) | None |
| `com.bootindustries.mlx-lm-8082` | LFM2.5-1.2B (Nan) | None |
| `com.bootindustries.mlx-lm-8083` | Qwen3.5-9B (on-demand) | None |
| `com.bootindustries.qdrant-mcp` | Qdrant MCP proxy :8446 | `QDRANT_API_KEY` |
| `com.bootindustries.research-mcp` | Research MCP proxy :8447 | `QDRANT_API_KEY` |
| `com.bootindustries.matrix-mcp-boot` | matrix-mcp Boot :8445 | `MATRIX_TOKEN_BOOT_PAN` |
| `com.bootindustries.matrix-mcp-coord` | matrix-mcp Coord :8448 | `MATRIX_TOKEN_COORD_PAN` |
| `com.bootindustries.coordinator-rs` | coordinator-rs | 4 Matrix tokens + `GRAPHITI_AUTH_TOKEN` + `OPENROUTER_API_KEY` |
| `com.bootindustries.auth-sidecar` | Auth sidecar :41914 | `AUTH_SECRET`, `AUTH_BCRYPT_HASH` |
| `com.bootindustries.gsd-sidecar` | GSD sidecar :41911 | None |
| `com.bootindustries.portal-caddy` | Portal Caddy :41910 | None |

Existing plists (from WHB006): Pantalaimon, Graphiti. Existing via Homebrew: Ollama. Docker/Colima: Qdrant, FalkorDB.

### 6.4 Config Changes Required Before Deployment

- `agent-config.yaml`: `graphiti_url` → `http://127.0.0.1:8444/sse`; add `devices.whitebox` block; all agents `default_device: whitebox`
- `Caddyfile`: bind address → `http://100.88.222.111:41910`; `root *` paths to Whitebox project root
- `Makefile`: `BLACKBOX` variable → `WHITEBOX := whitebox`; `REMOTE` path updated
- Verify Caddy on Whitebox has `forward_auth` module: `caddy list-modules | grep forward_auth`

---

## 7. IG-88 Trading — API Key Wiring

### 7.1 Keys Required

| Key | Source | Storage |
|-----|--------|---------|
| Jupiter API key | portal.jup.ag | Bitwarden SM `factory/agents` → `JUPITER_API_KEY` |
| Solana keypair | `solana-keygen new` on host | `~/.config/ig88/trading_wallet.json` (chmod 600) |

### 7.2 Credential Flow (Verified Clean)

```
Bitwarden vault → bws/mcp-env.sh [at MCP server startup only]
  → export JUPITER_API_KEY=<value>
    → process.env [jupiter-mcp Node.js process]
      → const JUPITER_API_KEY = process.env.JUPITER_API_KEY [index.ts:14]
        → handler functions as `apiKey` parameter
          → HTTP header: "x-api-key": apiKey → Jupiter REST API

NEVER appears in: LLM context, Matrix messages, coordinator-rs context, git history
```

The Solana keypair is NOT referenced anywhere in jupiter-mcp source. For live execution, `jupiter_swap` requires a pre-signed transaction — signing occurs outside the MCP server boundary. The keypair never enters the coordinator context window.

### 7.3 Guardrails (Hard-Coded in swap.ts)

- `MAX_POSITION_PCT = 0.20` — no trade > 20% of wallet balance
- `MAX_DAILY_LOSS_PCT = 0.10` — halt if daily drawdown > 10%
- Paper mode: live execution blocked until `paperTradeCount >= 50`
- Capital floor: $200-800 USDC (edge validation budget, not profit target)

### 7.4 Verification Checklist

- [ ] `jupiter_price([SOL_MINT])` returns valid price
- [ ] `jupiter_quote(SOL→USDC, 1_000_000_000)` returns quote with `priceImpactPct`
- [ ] `jupiter_swap(quote, dryRun: true)` increments paper trade counter
- [ ] Hot wallet funded with USDC + ~0.05 SOL for gas
- [ ] Cold wallet address confirmed NOT present in ig88 source tree

---

## 8. IG-88 Trading — Revised Validation Protocol

**Supersedes** IG88006 success/failure criteria and IG88010 schedule. Incorporates all seven FCT032 research consultant caveats.

### 8.1 Primary Metric: Expectancy (Replaces WR%)

```
E = (WR × avg_win_R) - ((1 - WR) × avg_loss_R)
```

Win rate alone is not a valid go/no-go criterion. 87% of active crypto wallets lose money [FCT032]. Expectancy is the combined metric that determines long-run profitability.

### 8.2 Revised Success Criteria

| Metric | Minimum (Gate) | Target | Exceptional |
|--------|----------------|--------|-------------|
| **Expectancy** | **+0.08R** | +0.15R | +0.25R+ |
| Win Rate | 52% | 54% | 56%+ |
| R:R (avg win / avg loss) | 1.5:1 | 1.8:1 | 2.0:1+ |
| Sharpe (annualized) | 1.0 | 1.5 | 2.0+ |
| Regime diversity | 2 distinct regimes (15+ trades each) | 3 regimes | — |

### 8.3 Regime Diversity Requirement

100 trades in one regime proves nothing about regime transitions. The protocol requires a minimum of 2 distinct regime environments with ≥15 trades each.

**Added field in IG88006 trade log schema:**

```yaml
regime_label: "RISK_ON_TRENDING"    # NEW — granular classification
regime_entry_date: "2026-03-23"     # NEW
regime_age_days: 4                  # NEW
```

**Regime labels:** `RISK_ON_TRENDING`, `RISK_ON_VOLATILE`, `RISK_OFF_RANGING`, `RISK_OFF_DECLINING`

**Transition performance metric:** Calculate expectancy separately for trades within the first 5 sessions after a regime transition vs. steady-state. If transition expectancy is >0.05R worse, the system has a regime-blind spot.

### 8.4 Kill Switches — Beyond Drawdown

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Daily drawdown | > 10% of capital | Halt execution (existing, in swap.ts) |
| Consecutive losses | > 6 | Pause; require human restart |
| Regime confidence collapse | confidence < 0.40 for 3+ consecutive cycles | Halt new entries until confidence > 0.55 |
| Regime confidence volatility | swing > 0.30 in single cycle | Force UNCERTAIN regardless of output |
| Coordination breakdown | Governor approval rate < 50% over 20 cycles | Halt; run diagnostic |
| Expectancy decay | Rolling 20-trade expectancy < 0 | Mandatory review; no new entries without override |

### 8.5 Overfitting Checks

**Out-of-sample decay metric:** At each 25-trade checkpoint:

```
oos_decay_ratio = expectancy(last_25_trades) / expectancy(all_trades)
Flag if: oos_decay_ratio < 0.70
```

**Self-improvement constraint:** Prompt changes must be documented with version tag (`prompt_version: v1.2`). Changes that improve apparent performance on already-seen trades are disallowed — refinements must be prospective.

### 8.6 Coordination Tax Monitoring

At each 25-trade block, log:
- Governor approval rate (threshold: ≥0.55)
- Scanner rank correlation with outcomes (threshold: ≥0.20)
- Average cycle latency (threshold: <240s)
- Governor confidence calibration gap (high_conf_wr - low_conf_wr > 0.05)

**Degradation diagnostic:** If triggered, run single-agent version of the same cycle. If single-agent outperforms 5-agent by >0.05R, collapse toward skill-on-one-agent architecture.

### 8.7 Revised Go/No-Go Matrix

**GO — ALL must be true:**
- Expectancy ≥ +0.08R over 100 trades
- Win Rate ≥ 52%
- ≥2 distinct regime environments (≥15 trades each)
- No active kill switch triggers
- Max consecutive losses ≤ 6; max drawdown ≤ 15%
- Governor approval rate ≥ 0.55 over final 25 trades
- OOS decay ratio ≥ 0.70 over final 25 trades

**NO-GO — ANY triggers:**
- Expectancy negative or < +0.05R after 100 trades
- Win rate < 50% after 100 or < 45% after 50 (early termination)
- Regime diversity not met after 100 trades (extend, don't archive)
- Regime confidence collapse fired > 5 times
- Max consecutive losses > 8
- OOS decay ratio < 0.50 (strong overfitting)
- Single-agent outperforms 5-agent by > 0.05R

**EXTEND to 150-200 trades when:**
- Regime diversity not yet met (insufficient transitions, not agent failure)
- Expectancy 0.05-0.08R (marginal — need larger sample)
- High variance (Sharpe < 0.8 but expectancy positive)

---

## 9. Documentation Updates Required

### 9.1 CLAUDE.md Files

| File | Change |
|------|--------|
| `~/dev/factory/CLAUDE.md` | Port scheme: all Blackbox entries → Whitebox IP |
| `~/dev/blackbox/CLAUDE.md` | Full topology rewrite; mark Blackbox retired |
| `~/dev/whitebox/CLAUDE.md` | Update port table (Phase 2b services shown as "Planned" → LIVE) |
| MEMORY.md (factory project) | Update port scheme, topology, "Current broken" list |

### 9.2 Config Files

| File | Change |
|------|--------|
| `~/dev/blackbox/src/agent-config.yaml` | `graphiti_url` → `127.0.0.1:8444`; `default_device` → `whitebox`; add `devices.whitebox` |
| `~/.mcp.json` (Cloudkicker) | All MCP URLs → `100.88.222.111` |
| Portal `Makefile` | `BLACKBOX` → `WHITEBOX`; update `REMOTE` path |
| Portal `Caddyfile` | Bind address → `100.88.222.111:41910` |

### 9.3 PREFIX Docs

| Document | Change |
|----------|--------|
| FCT029 | §1.1 Blackbox → retired; §8.2-8.3 → complete; add FCT033 cross-ref |
| BKX125 | Fill resolved username; Phase 2/3 checklists → complete |
| BKX122 | Status → Active; record actual bws UUIDs post-provisioning |

---

## 10. E2EE Cutover Plan

### Gate Condition (FIRM)

**Do not begin until all three agents (@boot, @ig88, @kelk) have been stable on Pantalaimon for 7 consecutive days without token failures, sync errors, or coordinator restarts.**

### Why After Blackbox Retirement

All services co-located on Whitebox → single host surface for cutover. Stop Pantalaimon, rebuild coordinator, restart. No cross-host state to reconcile.

### Prerequisites

- [ ] Phase 2c complete — all services on Whitebox
- [ ] 7-day stability gate satisfied
- [ ] 8 secrets provisioned: 4 passwords + 4 recovery keys (Boot, IG-88, Kelk, Coord)
- [ ] `bws` accessible on Whitebox
- [ ] IdentityRegistry tested in non-production room

### Procedure

1. Record current device IDs (will be invalidated)
2. Archive `pan.db`: `cp ~/.local/share/pantalaimon/pan.db ~/backups/pan.db.$(date +%F)`
3. Stop Pantalaimon: `launchctl stop pantalaimon && launchctl disable pantalaimon`
4. Compile: `cargo build --release --features native-e2ee`
5. Update `agent-config.yaml`: remove `pantalaimon_url`, add `e2ee` block, remove `token_file` entries
6. Restart coordinator; watch for crypto init sequence (2-4 min per identity)
7. Smoke test: DM each agent from Element
8. **Cross-signing ceremony (BKX058)** — mandatory; old BKX065 ceremony was for Pantalaimon device IDs
9. Remove old `MATRIX_TOKEN_*_PAN` entries from Secrets Manager
10. 48-hour monitoring window — no changes

### Rollback

1. `launchctl enable pantalaimon && launchctl start pantalaimon`
2. Deploy previous coordinator binary (without `native-e2ee`)
3. Restore `token_file` entries in config
4. Restart coordinator

Pantalaimon retained (disabled) for 30 days post-cutover.

---

## 11. Execution Timeline

### Phase A — Restore Agent Health (Day 1)

**Entry:** Coordinator running on Blackbox. Boot active. IG-88 and Kelk offline.

| Step | Action | Depends On | Est. |
|------|--------|-----------|------|
| A1 | SSH to Whitebox — start MLX-LM :8080-8083 | None | 10 min |
| A2 | Verify Graphiti responds | A1 | 5 min |
| A3 | Retrieve IG-88/Kelk passwords from Bitwarden; login to Pantalaimon on Whitebox :8009; write tokens to Blackbox `~/.config/ig88/` | A1 | 20 min |
| A4 | Fix coordinator systemd `MATRIX_TOKEN_COORD_PAN` injection | A3 | 10 min |
| A5 | Restart coordinator-rs | A4 | 5 min |
| A6 | Verify all 3 agents respond in Matrix | A5 | 10 min |
| A7 | `make sync` portal security fixes to Blackbox | A6 (can overlap) | 15 min |
| A8 | Commit + push outstanding changes | A7 | 15 min |

**Exit:** All agents online. Portal at A- on production. No uncommitted changes. Stability gate clock starts.

### Phase B — IG-88 API Key Wiring (Day 1-2)

**Entry:** Phase A steps A1-A5 complete. **Note:** B5 (connectivity verification) requires Phase A fully complete.

| Step | Action | Depends On |
|------|--------|-----------|
| B1 | Obtain Jupiter API key from portal.jup.ag | None |
| B2 | Generate Solana keypair on host | None |
| B3 | Store in age-encrypted `.env` + Bitwarden SM | B1, B2 |
| B4 | Fund hot wallet ($200-800 USDC + 0.05 SOL) | B3 |
| B5 | Verify `jupiter_price` and `jupiter_quote` via IG-88 dispatch | Phase A complete, B3 |

**Exit:** Jupiter tools return live data. Hot wallet funded.

### Phase 2c — Blackbox Retirement (Days 2-5)

**Entry:** BWS setup complete. Phase A exit met.

| Step | Action |
|------|--------|
| 2c.1 | Bitwarden Secrets Manager setup (Section 5) |
| 2c.2-2c.4 | Create all 12 launchd plists (Section 6) |
| 2c.5 | Deploy coordinator + matrix-mcp to Whitebox; start via launchd |
| 2c.6 | Begin 48h parallel operation |
| 2c.7 | **Degradation testing:** kill each Whitebox service one at a time; verify graceful degradation, not cascading failure |
| 2c.8 | Promote Whitebox; stop Blackbox coordinator |
| 2c.9 | Decommission Blackbox (stop services, BKX119 cleanup, power down) |
| 2c.10 | Deploy RP5 watchdog cron (Section 4.3) |
| 2c.11 | Commit + push; update all docs (Section 9) |

**Exit:** All services on Whitebox via persistent launchd. Blackbox powered down. RP5 watchdog operational.

### Phase C — Paper Trading Validation (Weeks 2-5)

**Entry:** Phase B exit met. Coordinator stable on Whitebox.

100+ trades across 2+ regime environments. Expectancy as primary metric. See Section 8 for full protocol.

**Exit:** All Section 8.7 GO criteria met. Written summary committed.

### Phase D — megOLM Cutover (Week 6+)

**Entry (FIRM):** 7 consecutive days of agent stability on Pantalaimon AND Phase 2c complete.

See Section 10 for full procedure.

**Exit:** Native Megolm operational. All devices verified. 48h monitoring complete.

### Concurrency Note

Phase C and Phase D are independent. Phase D gates on stability time, not trading results. Both can proceed in parallel if the stability gate is met during Phase C.

---

## 12. Risk Register

### Infrastructure

| Risk | L/I | Mitigation |
|------|-----|-----------|
| Whitebox single-host failure (power, disk, kernel panic) | M/H | RP5 watchdog alerts within 4 min; Blackbox retained as cold standby for 30 days; document 1-hour cold restore procedure |
| launchd plist failures after reboot | H/M | Test each plist via `launchctl unload/load` during setup; cold-boot validation in Phase 2c; RP5 watchdog catches silent failures |
| Colima Docker bridge failure after macOS sleep | M/M | Configure Colima autostart; recovery: `colima stop && colima start` |
| MLX-LM memory pressure (17GB peak + E2EE clients) | L/M | Qwen 9B (:8083) on-demand only; monitor `vm_stat` during parallel window |

### Trading

| Risk | L/I | Mitigation |
|------|-----|-----------|
| Overfitting / backtest-to-live degradation | H/H | Regime diversity requirement; expectancy as primary metric; OOS decay monitoring; prospective-only prompt tuning |
| Survivorship bias in signal development | M/H | Log NO_TRADE cycles with counterfactual outcomes; explicit review question at each 25-trade checkpoint |
| Forecast layer gap (backward-looking only) | H/M | Architectural acceptance; position sizing limits damage floor; LunarCrush provides partial forward coverage |
| Coordination Tax degradation | M/M | Monitor Governor override rate; if >20% for 30+ trades, collapse one agent |
| Hot wallet compromise | L/H | Limited capital ($200-800); keypair never in LLM context; rotate on any compromise indicator |

### Security

| Risk | L/I | Mitigation |
|------|-----|-----------|
| Credential leakage via LLM context | L/H | bws injection at startup; pre-commit hook; jupiter-mcp reads from env only |
| E2EE cutover failure | M/H | Rollback plan rehearsed; Pantalaimon retained 30 days; test each identity in staging first |
| BWS vault unreachable at reboot | L/H | age-encrypted fallback retained; manual recovery runbook documented |

---

## 13. Open Decisions

### Resolved by This Plan

| Decision | Resolution |
|----------|-----------|
| Blackbox post-Whitebox role (FCT029 §11) | **Full retirement.** RP5 repurposed as dumb watchdog. |
| Pantalaimon vs. E2EE timing (FCT029 §11) | **E2EE after Whitebox retirement.** WHB006 already migrated Pantalaimon; cutover is Phase D after stability gate. |

### Remaining Unresolved

| Decision | Status | Trigger |
|----------|--------|---------|
| Whitebox macOS username | **Must resolve before Phase 2c** — all plist paths depend on it |
| Class index finalization (8-class scheme) | Defer until GSD SQLite migration makes usage patterns observable |
| GSD sidecar naming | Defer until SQLite evolution (job.10.006.0032) |
| Factory rebrand ("DreamFactory" collision) | Low priority; defer until public deployment |
| Job sync transport (Tailscale vs rsync) | Simplified by single-host; decide at SQLite migration |
| IG-88 agent count (5 vs 4) | **Observe during Phase C.** If Governor override rate >20% for 30+ trades, collapse one agent |
| Degradation testing scope for 48h window | **Define test matrix before Phase 2c.6.** Minimum: Graphiti, one matrix-mcp, FalkorDB, one MLX-LM |
| Stability gate definition (calendar vs loop count) | 7 calendar days is the working definition; operator judgment at the gate |

---

## 14. References

[1] FCT029, "Factory Consolidated Plan — Architecture, Recovery, and Roadmap," 2026-03-22.

[2] FCT032, "Strategy Vet: Research Vault Findings vs. Compiled Assessment," 2026-03-23.

[3] FCT030, "Sprint Completion — Port Allocation, GSD SQLite Design, and Git Housekeeping," 2026-03-22.

[4] FCT031, "Next Steps Forward," 2026-03-23.

[5] BKX122, "Secrets Manager — Headless Machine Credentials (Whitebox)," 2026-03-15.

[6] BKX126, "Pantalaimon to Native Megolm E2EE Migration," 2026-03-15.

[7] BKX074, "Greybox 2.0 Hardware Recommendations," 2026-03-14.

[8] WHB006, "Phase 2b Sprint B — FalkorDB, Graphiti, Pantalaimon Migration," 2026-03-19.

[9] IG88003, "Strategic Foundation and Edge Validation," 2026-01-24.

[10] IG88006, "Validation Protocol," 2026-01-24.

[11] IG88029, "Jupiter Integration — Execution Capabilities," 2026-02-19.

[12] IG88030, "Dexscreener Integration," 2026-02-19.

[13] BKX058, "Element Cross-Signing Procedure."

[14] BKX065, "Cross-Signing Ceremony Completion," 2026-02-19.
