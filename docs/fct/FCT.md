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

---

## Quick Reference

- **Active agents:** IG-88 (trading), Boot (projects/dev), Kelk (personal assistant)
- **Coordinator:** coordinator-rs (Rust binary, Matrix substrate, HMAC approvals)
- **Inference:** Local MLX models — Qwen, Nanbeige, LFM series
- **Memory:** Graphiti (temporal KG) + Qdrant (vector) + FalkorDB
- **Governance:** ATR002 frozen harness + Loop Spec

---

*Auto-generated index. Run `~/dev/scripts/generate-prefix-indexes.sh` to regenerate.*
