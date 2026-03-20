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
- **Fonts:** Geist Pixel Grid (display), Geist Mono UltraLight (body/mono)
- **Deploy:** `make sync` from `portal/` — rsyncs to Blackbox :41910
- **Tests:** `pnpm test` (vitest, 25 tests across 13 files)
- **Build:** `pnpm build` — outputs to `portal/dist/`
- **Brand:** "dreamfactory" (hero header)

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
- Font trial system available on Topology page for design experimentation

## Port Scheme

| Port | Service |
|------|---------|
| :41910 | Portal Caddy (live) |
| :41911 | GSD sidecar (jobs.json + status) |
| :41920-41939 | Preview slots |
| :41940-41949 | Development |
| :41950-41959 | Coordinator HTTP API (future) |
