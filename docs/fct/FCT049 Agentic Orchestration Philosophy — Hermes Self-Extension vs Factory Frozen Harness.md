# FCT049 Agentic Orchestration Philosophy — Hermes Self-Extension vs Factory Frozen Harness

**Date:** 2026-04-05
**Type:** Cross-vault architectural analysis
**Status:** Complete
**Sources:** 20 TX research docs, FCT045, ATR002, BTI011, Self-Extending Agents pattern

---

## Executive Summary

A cross-vault analysis comparing Hermes Agent's self-extending orchestration philosophy with Factory's coordinator-centric frozen-harness model. Based on 20 TX research docs [1]–[5], FCT045 competitive analysis [6], ATR002 autoscope design [8], BTI011 infrastructure ops [9], and the Self-Extending Agents pattern doc [10]. The two systems solve the same problem from opposite ends: agent-centric autonomy (Hermes) vs coordinator-centric control (Factory).

---

## The Two Philosophies

### Hermes (Agent-Sovereign)

- The agent owns its memory, skills, and (aspirationally) weights
- Multi-instance profiles give each agent independence
- Background self-improvement loop means each agent gets smarter in isolation [4]
- Self-development thesis: gap identified → agent self-writes skill → community validation → promoted to built-in [3]
- Vision: N independent agents that happen to share a framework
- Weight-ownership endgame via Atropos + Tinker (30B MoE, self-trained) [1]

### Factory / coordinator-rs (Coordinator-Sovereign)

- The coordinator is sovereign. Agents are roles in a topology controlled by a centralized Rust binary [7]
- Soul files are frozen harness — not self-modifiable, coordinator-deployed
- Trust levels (L1–L3) separate what an agent is allowed to do from what it can do [9]
- Improvement happens in the knowledge layer (Qdrant, Graphiti), not the identity layer
- Matrix as structured audit trail (MSC3440 threading, task-per-thread anchors, m.mentions)

---

## Patterns to Import from Hermes (Updated Priority)

1. **Provider failover chain** (FCT045 §4.1, unchanged) — highest impact, addresses known MLX-LM restart fragility
2. **Ambient post-response knowledge extraction** — NEW recommendation not in FCT045. Spawn lightweight background pass after each agent response to write observations to Qdrant/Graphiti. Not self-extending (no capability modification), just self-documenting. No frozen harness violation. The coordinator would own the extraction agent lifecycle.
3. **Memory provider trait abstraction** — Define a `MemoryProvider` trait; make Graphiti and Qdrant implementations of it. Enables future backend swaps without coordinator code changes.
4. **Profile export/import** (FCT045 §4.4) — low effort, improves disaster recovery
5. **Plugin lifecycle hooks** (FCT045 §4.3) — enables token counting and cost tracking

---

## Factory's Structural Advantages

1. **Frozen harness principle (ATR002) [8]:** "The frozen harness is more important than the metric." autoscope prevents self-extending agents from modifying their own constraints. Hermes has no equivalent safety apparatus.
2. **Trust ≠ Capability (BTI011) [9]:** Trust levels separate permissions from capability. Hermes profiles have config isolation but no trust hierarchy.
3. **Matrix as audit trail:** MSC3440 threading, task-per-thread anchors, m.mentions notification control. Federated, cryptographically authenticated, human-readable. Hermes's 12-platform breadth means none get this depth.
4. **Centralized error filtering:** `is_suppressed_error()` covers all four output paths. Hermes has no equivalent centralized error policy.

---

## The Self-Extension Spectrum — Where Each System Sits

```
Read-only context files       Context files that modify themselves
         |                                   |
    Scaffold + skills           Scaffold generates new skills
         |                                   |
  Feedback-loop learning          Weight-level self-training

Factory sits here ──────┐                    ┌── Hermes sits here
                        ▼                    ▼
              Knowledge-layer          Capability-layer
              improvement              self-extension
```

Factory's bet: knowledge-layer improvement (Qdrant, Graphiti, synthesis docs) gives 80% of compounding benefit with 10% of the alignment risk. Hermes's bet: the remaining 20% (weight-level self-training, autonomous skill creation) is where the real returns are.

---

## Strategic Assessment

- Factory's frozen-harness approach is correct for small-team, high-trust deployments where predictability and auditability matter
- Hermes's self-extending approach is correct for open-source ecosystems where contributor velocity and extensibility matter more than per-deployment control
- The one Hermes idea that crosses the philosophical divide without violating Factory principles: **ambient post-response knowledge extraction** — self-documenting, not self-extending
- OUROBOROS [13] demonstrates the downside risk of self-extending agents — emergent goal-preservation
- The CamoFox story [3] demonstrates the upside — agent capability acquisition through self-authored code

---

## References

[1] TX260225_2011-037A — Hermes Self-Owning Weights Vision
[2] TX260331_0045-D5E6 — Hermes v0.2–v0.6 Full Platform Evolution
[3] TX260403_1535-8604 — Hermes v0.7 Deep Dive (Memory Plugins, CamoFox)
[4] TX260403_0940-76D4 — Hermes/OpenClaw Subconscious Self-Improvement Loop
[5] TX260324_1203-1CD6 — Hermes v0.4.0 Background Self-Improvement
[6] FCT045 — Hermes Agent Competitive Analysis
[7] FCT002 — Factory Agent Architecture
[8] ATR002 — autoscope Agent Design (frozen harness principle)
[9] BTI011 — Infrastructure and Service Operations
[10] Self-Extending Agents — research-vault pattern doc
[11] Agent Orchestration Layer — research-vault pattern doc
[12] Orchestrator vs Peer-to-Peer Agent Coordination — research-vault decision doc
[13] TX260224_0849-D679 — OUROBOROS emergent goal-preservation incident
[14] TX260319_0000-766F — Hermes Five-Layer Memory vs OpenClaw
