# FCT — Factory Documentation Index

**Repo:** `~/dev/factory/` | **Prefix:** FCT

Map of content (MOC) for Factory agent infrastructure documentation.

---

## Documents

| # | Title | Date | Summary |
|---|-------|------|---------|
| FCT001 | [FACTORY](FCT001%20FACTORY.md) | 2026-03 | System architecture and strategic plan |
| FCT002 | [Factory Agent Architecture — Roles, Models, and Autonomous Loop Design](FCT002%20Factory%20Agent%20Architecture%20%E2%80%94%20Roles%2C%20Models%2C%20and%20Autonomous%20Loop%20Design.md) | 2026-03-16 | Agent roles, model tiers, loop design |
| FCT003 | [Model Assignment Review — Nemotron 3 Nano 4B and March 2026 Model Landscape](FCT003%20Model%20Assignment%20Review%20%E2%80%94%20Nemotron%203%20Nano%204B%20and%20March%202026%20Model%20Landscape.md) | 2026-03-17 | Boot/IG-88/Kelk/Nan model review; Nemotron-3-Nano-4B corrections; context window table; landscape survey |
| FCT004 | [Paperclip vs Factory — Architecture Study and Adoption Assessment](FCT004%20Paperclip%20vs%20Factory%20%E2%80%94%20Architecture%20Study%20and%20Adoption%20Assessment.md) | 2026-03-17 | Full 4-agent study; 24-feature parity matrix; ADOPT/BORROW/LEARN/SKIP; 4 Rust implementation sketches; Matrix substrate analysis |
| FCT005 | [Hermes Agent — Fit Assessment for Paperclip x Factory Workflow](FCT005%20Hermes%20Agent%20%E2%80%94%20Fit%20Assessment%20for%20Paperclip%20x%20Factory%20Workflow.md) | 2026-03-17 | Three-way Hermes vs Paperclip vs Factory matrix; scheduling and memory model comparison; verdict: SKIP runtime, BORROW NL scheduler concept |
| FCT006 | [Factory Portal — Gap Analysis and Roadmap to Paperclip-Parity UX](FCT006%20Factory%20Portal%20%E2%80%94%20Gap%20Analysis%20and%20Roadmap%20to%20Paperclip-Parity%20UX.md) | 2026-03-17 | 13-feature gap matrix vs Paperclip; 4-phase roadmap (approval inbox, live transcripts, budget UI, analytics); backend endpoint requirements; vanilla JS implementation strategy |
| FCT007 | [Paperclip Deep-Dive — 14 Additional Patterns for Factory](FCT007%20Paperclip%20Deep-Dive%20%E2%80%94%2014%20Additional%20Patterns%20for%20Factory.md) | 2026-03-17 | 3-agent second-pass study; 14 new patterns (#5-#18); patterns #5-#8 implemented (budget incidents, session compaction, runtime state, event streaming); #9-#18 catalogued; cross-cutting conventions; dependency graph |
| FCT008 | [Sprint Complete — Paperclip x Factory Gap Analysis and Implementation](FCT008%20Sprint%20Complete%20%E2%80%94%20Paperclip%20x%20Factory%20Gap%20Analysis%20and%20Implementation.md) | 2026-03-17 | Sprint report: coordinator-rs migrated to factory/; 6 of 18 Paperclip patterns implemented (task lease, approval gates, budget, context mode, runtime state, run events); 29/29 tests; commit b76a052 |
| FCT009 | [Autoscope Integration — Autoresearch Loop Engine for coordinator-rs](FCT009%20Autoscope%20Integration%20%E2%80%94%20Autoresearch%20Loop%20Engine%20for%20coordinator-rs.md) | 2026-03-17 | Three-agent research sprint; karpathy/autoresearch upstream analysis; autoscope Loop Spec schema and 5 loop types; 10-gap coordinator-rs integration analysis; 3-layer frozen harness enforcement; 6-phase implementation roadmap |
| FCT010 | [Autoscope Loop Engine — Sprint Completion Summary](FCT010%20Autoscope%20Loop%20Engine%20%E2%80%94%20Sprint%20Completion%20Summary.md) | 2026-03-17 | Sprint report: loop_engine.rs (310 lines, 8 tests); LoopSpec/ActiveLoop/LoopManager; 2 approval gate types; 6 run event variants; frozen harness enforcement in coordinator.rs; 37/37 tests passing |
| FCT011 | [Factory Portal v8 — Design Overhaul and Deployment](FCT011%20Factory%20Portal%20v8%20%E2%80%94%20Design%20Overhaul%20and%20Deployment.md) | 2026-03-20 | Portal v8 design pass: indigo palette, Input Sans/Inter/Input Mono font stack, dark+light mode with useTheme hook, hotkey navigation (1-7 + backslash), enriched 5-section TopologyPage, deployed at :41988 on Blackbox |
| FCT012 | [Factory — Task Backlog and Work Item Registry](FCT012%20Factory%20%E2%80%94%20Task%20Backlog%20and%20Work%20Item%20Registry.md) | 2026-03-20 | Canonical work item registry: 80+ tasks across 8 categories (infrastructure, agent capabilities, agent loops, portal UX, research, coordinator-rs, curriculum-derived, completed). Task schema definition. Dependency map. Data format recommendation. |
| FCT013 | [Factory — Coordinator-Native Task Tracking Architecture](FCT013%20Factory%20%E2%80%94%20Coordinator-Native%20Task%20Tracking%20Architecture.md) | 2026-03-20 | Layer 3 architecture doc: bridge FCT012 markdown backlog with portal tasks.json via coordinator-rs. 4-phase migration (sync script, read-only, write integration, full authority). task_store.rs design, RunEvent task_id extension, data model additions, Paperclip pattern mapping. |
| FCT014 | [Factory — Task Sync, Portal Density, and Port Reorganization Sprint](FCT014%20Factory%20%E2%80%94%20Task%20Sync%2C%20Portal%20Density%2C%20and%20Port%20Reorganization%20Sprint.md) | 2026-03-20 | Sprint report: sync-fct012.py (102 tasks, 4 table variants); FCT013 architecture doc; Caddy handle-block routing fix; portal density cleanup (6 components); port reorganization (:41910 production scheme + VERSIONS.md). 25/25 tests passing. |
| FCT015 | [Factory — Job Registry Architecture and Migration](FCT015%20Factory%20%E2%80%94%20Job%20Registry%20Architecture%20and%20Migration.md) | 2026-03-20 | Job registry architecture: migration from monolithic tasks.json to individual YAML job files; `job.##.###.####` TCP/IP-inspired addressing scheme (domain/class/address); governance rules; portal integration; FCT012 migration plan with audit findings. |
| FCT016 | [Factory — Job Registry Migration Sprint Report](FCT016%20Factory%20%E2%80%94%20Job%20Registry%20Migration%20Sprint%20Report.md) | 2026-03-20 | Sprint report: 102 tasks migrated to 99 YAML job files; 3 culled, 2 marked done, 7 deferred; 4-subagent Qdrant audit applied; portal updated to jobs.json; agent instruction files updated; 25/25 tests passing. |
| FCT017 | [Factory Portal — Topology Flow, Registry Tables, Font System, and Visual Texture](FCT017%20Factory%20Portal%20%E2%80%94%20Topology%20Flow%2C%20Registry%20Tables%2C%20Font%20System%2C%20and%20Visual%20Texture.md) | 2026-03-20 | Topology page overhaul: escalation chain flow layout with arrow connectors; inline-editable domain/class registry tables; 12-font trial system (Geist Pixel Grid + Geist Mono UltraLight selected); CSS dual-layer dot grid texture; footer translucence; "dreamfactory" rebrand; 25/25 tests passing. |
| FCT018 | [Factory Portal — Mobile Optimization and UX Polish Sprint](FCT018%20Factory%20Portal%20%E2%80%94%20Mobile%20Optimization%20and%20UX%20Polish%20Sprint.md) | 2026-03-21 | Sprint report: unified shell width (min(1410px, 92vw)); job card checkbox/description/action fixes; Loop Controls composite row + 2x2 mobile grid; System Topology vertical stack; agent detail compact cards + single-column run table; iOS zoom prevention; horizontal overflow fixes (min-width:0); Objects hotkey hints hidden on mobile. 17/17 tests passing. |

---

## Quick Reference

- **Active agents:** IG-88 (trading), Boot (projects/dev), Kelk (personal assistant)
- **Coordinator:** coordinator-rs (Rust binary, Matrix substrate, HMAC approvals)
- **Inference:** Local MLX models — Qwen, Nanbeige, LFM series
- **Memory:** Graphiti (temporal KG) + Qdrant (vector) + FalkorDB
- **Governance:** ATR002 frozen harness + Loop Spec

---

*Auto-generated index. Run `~/dev/scripts/generate-prefix-indexes.sh` to regenerate.*
