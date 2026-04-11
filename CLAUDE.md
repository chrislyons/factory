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
├── scripts/          # Build tooling + agent-add.sh (provisioning) + agent-console.sh (tmux)
├── plists/           # launchd plists (gitignored, deployed manually)
├── docs/fct/         # PREFIX docs (FCT001–FCT066+)
└── CLAUDE.md         # This file
```

## Portal

- **Stack:** Vite + React + TypeScript, pnpm
- **Fonts:** Geist Pixel Square (display), Geist Mono UltraLight (body/mono)
- **Deploy:** `make sync` from `portal/` — builds, git-pushes source + rsyncs dist/ to Whitebox :41910
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
| :41200 | Pantalaimon (E2EE proxy) |
| :41400 | Matrix MCP Coord |
| :41401 | Matrix MCP Boot |
| :41430 | FalkorDB (graph DB) |
| :41440 | Graphiti MCP (SSE) |
| :41450 | Qdrant HTTP |
| :41455 | Qdrant gRPC |
| :41460 | Qdrant MCP (projects-vault) |
| :41470 | Research MCP (research-vault) |
| :41910 | Portal Caddy (live) |
| :41911 | GSD sidecar (jobs.json + status) |
| :41914 | Auth sidecar (cookie auth) |
| :41920-41939 | Preview slots |
| :41940-41949 | Development |
| :41950-41959 | Coordinator HTTP API (planned) |
| :41961 | MLX inference — Boot dedicated (gemma-4-e4b-it-6bit) |
| :41962 | MLX inference — Kelk dedicated (gemma-4-e4b-it-6bit) |
| :41960 | MLX inference — reserved (aux/E2B candidate) |
| :41988 | MLX inference — IG-88 hardware slot (idle; IG-88 runs on OpenRouter since FCT066) |

> **Blackbox retired 2026-03-23.** RP5 serves as dumb watchdog only (cron health checks → Matrix alerts).
> **IG-88 on OpenRouter since FCT066 (2026-04-10).** Boot + Kelk on local MLX E4B.

## Agent Console (FCT048)

- **Feature:** Shared tmux sessions for observing/interacting with agents from any Tailnet SSH client
- **Config:** `agent_console_enabled: bool` + `agent_tmux_socket_dir` in Settings (default: off)
- **Script:** `scripts/agent-console.sh <agent> [--attach|--watch|--list]`
- **Sessions:** `agent-<name>` tmux sessions with 250k scrollback, named sockets in `/tmp/tmux-nesbitt/`
- **Rendering:** Coordinator writes `[HH:MM] matrix/sender message` (input) and `[HH:MM] agent -> tool_call/response` (output) to pty
- **Plist:** `plists/com.bootindustries.agent-console-boot.plist` (RunAtLoad + KeepAlive)

