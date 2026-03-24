# Factory — Claude Code Configuration

**Repo:** `~/dev/factory/` | **PREFIX:** FCT | **Branch:** main

---

## Structure

```
factory/
├── portal/           # React multi-page app (Vite, pnpm)
├── coordinator/      # Rust orchestration binary (coordinator-rs)
├── agents/           # Agent planning repos (boot, ig88, kelk — submodules)
├── jobs/             # Job YAML files + registry.yaml
├── scripts/          # Build tooling (build-jobs-json.py)
├── docs/fct/         # PREFIX docs (FCT001–FCT017+)
└── CLAUDE.md         # This file
```

## Portal

- **Stack:** Vite + React + TypeScript, pnpm
- **Fonts:** Geist Pixel Square (display), Geist Mono UltraLight (body/mono)
- **Deploy:** `make sync` from `portal/` — rsyncs to Whitebox :41910
- **Tests:** `pnpm test` (vitest, 17 tests across 9 files)
- **Build:** `pnpm build` — outputs to `portal/dist/`
- **Brand:** "dreamfactory" (hero header, 16px/10px)
- **Nav tabs (5):** Jobs, Loops, Docs, Stats, Config (hotkeys 1-5)
- **Landing page:** Jobs Tracker (`jobs.html`, aliases `dashboard-v4.html`; nav button stays "Jobs")
- **Shell width:** min(1400px, 92vw) all viewports (no mobile override)
- **Mobile (<980px):** Nav hidden, page title h1 becomes nav dropdown, topology sections stack vertically
- **Header order:** [Command Palette] [SyncClock] [Theme Toggle]
- **Merged pages:** Approvals→Loops, Budget→Analytics
- **Docs page:** Combines RepoExplorer and Object Index as sub-tabs (nav button "Docs")
- **Stats page title:** Statistics (nav button "Stats")
- **Config page title:** Configuration (nav button "Config")
- **Retired:** Portal landing (redirects to Jobs), ApprovalsPage, BudgetPage

## Job Registry

- **ID scheme:** `job.DD.CCC.AAAA` (domain.class.address)
- **Files:** `jobs/<domain>/job.DD.CCC.AAAA.yaml`
- **Registry:** `jobs/registry.yaml` (domain + class definitions)
- **Build:** `python3 scripts/build-jobs-json.py` → `jobs.json`
- **Portal consumption:** `jobs.json` served via GSD sidecar on :41911

## Coordinator-rs

- **Location:** `coordinator/` (~11,600 lines Rust, 41 tests)
- **Build:** `cargo build` / `cargo test`
- **Config:** YAML-based (agents, rooms, settings, LLM providers)

## Conventions

- Commit format: `type(scope): description`
- Documentation: `docs/fct/FCT### Title.md`
- Never read: `node_modules/`, `dist/`, `target/`, `.DS_Store`
- Font trial system available on Config page for design experimentation

## Port Scheme

> Full master table: `infra/ports.csv`

**Factory Services (Whitebox 100.88.222.111):**

| Port | Service |
|------|---------|
| :6333-6334 | Qdrant (HTTP + gRPC) |
| :8009 | Pantalaimon (E2EE proxy) |
| :8440 | Matrix MCP Coord |
| :8442 | Qdrant MCP (projects-vault) |
| :8443 | Research MCP (research-vault) |
| :8444 | Graphiti MCP |
| :8448 | Matrix MCP Boot |
| :41910 | Portal Caddy (live) |
| :41911 | GSD sidecar (jobs.json + status) |
| :41914 | Auth sidecar (cookie auth) |
| :41920-41939 | Preview slots |
| :41940-41949 | Development |
| :41950-41959 | Coordinator HTTP API (planned) |
| :41960-41963 | MLX-LM inference (4 model slots) |

> **Blackbox retired 2026-03-23.** RP5 serves as dumb watchdog only (cron health checks → Matrix alerts).

## Security Notes (FCT040)

**Red-team audit 2026-03-24 — 25 findings, 7 remediated this session:**

| Status | Finding | Fix |
|--------|---------|-----|
| ✅ Fixed | F-01: BWS UUIDs in git (plists/) | `plists/` added to `.gitignore`, `git rm --cached` |
| ✅ Fixed | F-02: Hardcoded bcrypt hash in auth.py | Fail-closed on missing `AUTH_BCRYPT_HASH` |
| ✅ Fixed | F-11: Login redirect DOM injection | Client-side path validation added |
| ✅ Fixed | F-16: JSON injection in watchdog.sh | `jq -n --arg` construction |
| ✅ Fixed | F-17: `StrictHostKeyChecking=no` | Changed to `accept-new` |
| ✅ Fixed | F-24: Docker `:latest` tag | Pinned to sha256 digest |
| ✅ Fixed | F-25: `npm install` in deploy script | Changed to `npm ci` |
| ✅ Fixed | F-03: Caddy cookie bypass → forward_auth | xcaddy build + Caddyfile rewrite |
| ⏳ Deferred | F-01 history purge | `git filter-repo` would rewrite all SHAs — deferred as low-risk (UUIDs only) |

**Caddy binary:** Whitebox runs `~/bin/caddy-forward-auth` (xcaddy-built with forward_auth support). Plist updated. Homebrew caddy kept as fallback at `/opt/homebrew/bin/caddy`.

**Remaining open:** F-04–F-25 (Rust changes, 0.0.0.0 binding, etc.) — see FCT040 for full list.

## Resilience Notes (FCT041)

**Power outage hardening — 2026-03-24:**

- **RunAtLoad** added to all 12 bootindustries LaunchAgents — Whitebox now self-heals after reboot
- **Pantalaimon** (`com.pantalaimon`) already had RunAtLoad + KeepAlive (separate plist, not in plists/)
- **Coordinator error relay** is now context-aware: auth errors suppressed during network degradation, flushed as single summary on recovery; non-auth errors always relay
- **Sync backoff**: exponential 1s→16s on consecutive failures (was: 3s flat with no backoff)
- **HUD label**: "Whitebox Status HUD" (was "Blackbox")
- **Deferred**: CircuitBreaker wiring to send path, task lease persistence, startup ordering (WaitForDependencies), ThrottleInterval tuning
