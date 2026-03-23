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

> Full master table: `~/dev/docs/ports.md`

**Factory Services (Whitebox 100.88.222.111):**

| Port | Service |
|------|---------|
| :41910 | Portal Caddy (live) |
| :41911 | GSD sidecar (jobs.json + status) |
| :41914 | Auth sidecar (cookie auth) |
| :41920-41939 | Preview slots |
| :41940-41949 | Development |
| :41950-41959 | Coordinator HTTP API (planned) |
| :41960-41963 | MLX-LM inference (4 model slots) |
| :6333-6334 | Qdrant (HTTP + gRPC) |
| :8009 | Pantalaimon (E2EE proxy) |
| :8444 | Graphiti MCP |
| :8446 | Qdrant MCP (projects-vault) |
| :8447 | Research MCP (research-vault) |

> **Blackbox retired 2026-03-23.** RP5 serves as dumb watchdog only (cron health checks → Matrix alerts).
