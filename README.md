# Factory

Operator control surface and orchestration infrastructure for the Boot Industries multi-agent system.

## Components

| Component | Description | Stack |
|-----------|-------------|-------|
| **Portal** | Multi-page operator dashboard | React, Vite, TypeScript |
| **Coordinator** | Agent orchestration and routing | Rust, Matrix E2EE |
| **Job Registry** | Task tracking via YAML job files | Python build script |
| **Hermes Agents** | Three persistent LLM agents (Boot, Kelk, IG-88) | Hermes v0.8.0, Matrix E2EE |
| **MLX Inference** | Local model serving (2x E4B + 26B SSD streaming) | mlx-vlm, flash-moe |

See [AGENTS.md](AGENTS.md) for the full agent topology, routing, and secrets reference.

## Portal

The portal is a React multi-page app deployed to Whitebox via Caddy (:41910).

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

## Agents

Three persistent Hermes agents on Whitebox (Mac Studio M1 Max, 32GB):

| Agent | Role | Main Model | Inference |
|-------|------|------------|-----------|
| **Boot** | Projects, dev, operations | Gemma 4 E4B (local :41961) | Fully local |
| **Kelk** | Personal advisor, reflection | Gemma 4 E4B (local :41962) | Fully local |
| **IG-88** | Trading, market analysis | Mimo-v2-Pro (Nous cloud) | Cloud |

Aux tasks (compression, search, skills) for Boot and Kelk route to Gemma 4 26B-A4B via SSD expert streaming on :41966 (flash-moe, ~3GB resident RAM, 5.4 tok/s).

All agents connect to Matrix with native E2EE (python-olm). See [AGENTS.md](AGENTS.md) for details.

## Documentation

PREFIX docs live in `docs/fct/`. Key documents:

- **FCT001** — Initial architecture and strategic plan
- **FCT011** — Portal v8 design overhaul
- **FCT015** — Job registry architecture
- **FCT017** — Topology flow, registry tables, font system, visual texture
- **FCT067** — SSD expert streaming, E2EE migration, Gemma tool call parser fix

## License

Private — Boot Industries.
