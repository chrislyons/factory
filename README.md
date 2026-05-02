# Factory

Operator control surface and orchestration infrastructure for the Boot Industries multi-agent system.

## Components

| Component | Description | Stack |
|-----------|-------------|-------|
| **Portal** | Multi-page operator dashboard | React, Vite, TypeScript |
| **Coordinator** | Agent orchestration and routing | Rust, Matrix E2EE |
| **Job Registry** | Task tracking via YAML job files | Python build script |
| **Hermes Agents** | Three persistent LLM agents (Boot, Kelk, IG-88) | Hermes v0.8.0, Matrix E2EE |
| **MLX Inference** | Local model serving (2× E4B-SABER + 1× E2B-SABER aux, tri-instance) | `mlx_lm.server` via FCT078 wrapper |

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
| **Boot** | Projects, dev, operations | Gemma-4-E4B-SABER raw (local :41961) | Fully local |
| **Kelk** | Personal advisor, reflection | Gemma-4-E4B-SABER raw (local :41962) | Fully local |
| **IG-88** | Trading, market analysis | Mimo-v2-Pro (Nous cloud) | Cloud |

Boot and Kelk each have a dedicated `mlx_lm.server` instance running through `scripts/mlx-lm-factory-wrapper.py` (FCT078 production wrapper: Metal+wired memory caps, 8-bit `QuantizedKVCache` patched in). E4B-SABER raw was selected by FCT091 bake-off as the only candidate that passes the full agentic-loop suite (autonomous, continuation, sprint, extended) at greedy decoding. A third lightweight Coord aux tier on `:41963` runs Gemma-4-E2B-SABER (DJLougen rev) for fast auxiliary subroutines — compaction, summarization, classification, intent triage — callable by Boot/Kelk or any Hermes aux slot (FCT092). Nemostein-3-Hermes-Omni 30B/3B is deprecated on `:41966` (`.deprecated` plist) and mutually exclusive with the Coord tier; hot-swap recipe documented in FCT092.

All agents connect to Matrix with native E2EE (python-olm). See [AGENTS.md](AGENTS.md) for details.

## Documentation

PREFIX docs live in `docs/fct/`. Key documents:

- **FCT001** — Initial architecture and strategic plan
- **FCT011** — Portal v8 design overhaul
- **FCT015** — Job registry architecture
- **FCT017** — Topology flow, registry tables, font system, visual texture
- **FCT067** — SSD expert streaming, E2EE migration, Gemma tool call parser fix
- **FCT091** — vllm-mlx bake-off, agentic-loop suite, dual-SABER production selection
- **FCT092** — Auxiliary inference tier: E2B-SABER on :41963 (Coord aux for compaction/summarization/triage)

## License

Private — Boot Industries.
