# Factory

Operator control surface and orchestration infrastructure for the Boot Industries multi-agent system.

## Components

| Component | Description | Stack |
|-----------|-------------|-------|
| **Portal** | Multi-page operator dashboard | React, Vite, TypeScript |
| **Coordinator** | Agent orchestration and routing | Rust, Matrix E2EE |
| **Job Registry** | Task tracking via YAML job files | Python build script |

## Portal

The portal is a React multi-page app deployed to Blackbox via Caddy.

```bash
cd portal
pnpm install
pnpm build        # production build → dist/
pnpm test         # vitest (17 tests, 9 files)
make sync         # deploy to Blackbox :41910
```

**Pages:** Jobs Tracker, Loops, Object Index, Analytics, System Topology (nav: Jobs/Loops/Objects/Analytics/System)
**Typography:** Geist Pixel Square (display), Geist Mono UltraLight (body). Font trial system on System Topology page.
**Shell:** `min(1400px, 92vw)` all viewports.

## Job Registry

99 jobs across 4 domains (System, Boot, IG-88, Kelk) and 8 classes. Each job is a YAML file under `jobs/`.

```bash
python3 scripts/build-jobs-json.py          # build jobs.json
python3 scripts/build-jobs-json.py --dry-run # preview
```

## Coordinator

Rust binary for multi-agent orchestration over Matrix E2EE. Budget tracking, approval gates, loop engine, task leases.

```bash
cd coordinator
cargo build
cargo test
```

## Documentation

PREFIX docs live in `docs/fct/`. Key documents:

- **FCT001** — Initial architecture and strategic plan
- **FCT011** — Portal v8 design overhaul
- **FCT015** — Job registry architecture
- **FCT017** — Topology flow, registry tables, font system, visual texture

## License

Private — Boot Industries.
