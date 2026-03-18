# FCT005 Hermes Agent — Fit Assessment for Paperclip x Factory Workflow

**Prefix:** FCT | **Repo:** ~/dev/factory/ | **Status:** Living document | **Related:** FCT004

---

## 1. Executive Summary

Two distinct "Hermes" projects exist in the AI agent space. Neither is a better fit than Factory + Paperclip borrows for IG-88's trading workloads, but one concept is worth borrowing.

**Hermes Agent (Nous Research, MIT)** is a general-purpose self-improving agent framework: ReAct loop, multi-level persistent memory, autonomous skill creation, multi-platform gateway. It excels at extensibility and multi-channel presence. It has no trading safety primitives — no approval gate types, no budget enforcement, no task lease mechanism, no cryptographic signing.

**Hermes Financial Research Framework (schnetzlerjoe, Python/LlamaIndex)** is a research-only investment analysis tool: SEC EDGAR, Yahoo Finance, macroeconomic agents, Excel/PDF output. It is not a trading execution system.

**Verdict:**
- Hermes Agent (Nous Research): SKIP as runtime. BORROW one concept: natural language task scheduling as a Factory skill.
- Hermes Financial Framework: SKIP entirely. Research-only; incompatible with IG-88's execution model.
- Factory + 4 Paperclip borrows (FCT004) remains the correct implementation path for IG-88.

---

## 2. What Hermes Is

### 2.1 Hermes Agent — Nous Research

**GitHub:** https://github.com/NousResearch/hermes-agent | **License:** MIT

General-purpose agentic framework built on:
- **ReAct loop** (observe → reason → act)
- **Multi-level memory**: short-term (inference context), long-term (Skill Documents via FTS5 + LLM summarization), user modeling (Honcho)
- **Autonomous skill creation** — agent encodes repeated workflows as portable Skill Documents at runtime
- **Multi-platform gateway** — single persistent agent across Telegram, Discord, Slack, WhatsApp, Signal, CLI
- **Subagent orchestration** — isolated conversations with Python RPC delegation
- **Natural language cron scheduling** — "every 3 hours, run deep_scan" parsed to cron
- **Serverless persistence** — Daytona/Modal: hibernates when idle, wakes on schedule or message
- **Model-agnostic** — Nous Portal, OpenRouter (200+ models), custom endpoints
- **40+ bundled skills** (MLOps, GitHub, research, web scraping)
- **Zero trading capabilities**

Key source components:

| Component | Role |
|-----------|------|
| `hermes/agent.py` | Main ReAct loop |
| `hermes/memory/skill_documents.py` | Long-term FTS5 memory |
| `hermes/memory/honcho.py` | User preference modeling |
| `hermes/gateways/` | Multi-platform adapters |
| `hermes/scheduler.py` | Natural language cron parser |
| `hermes/subagents/` | Isolated delegation framework |
| `hermes/skills/` | 40+ bundled skill library |

### 2.2 Hermes Financial Research Framework

**GitHub:** https://github.com/schnetzlerjoe/hermes | **Stack:** Python, LlamaIndex

Purpose-built for investment research and equity analysis. Not live trading.

**Capabilities:**
- Yahoo Finance: OHLCV, quotes, historical prices
- SEC EDGAR: filings, insider transactions, institutional holdings
- Economic time series data
- Specialized agents: SEC filings, macroeconomic, market data, report writing
- Output: Excel models, Word/PDF reports

**Relevance to IG-88:** Zero. IG-88 places real orders, monitors live market events, tracks realized P&L. This framework generates research documents. These are different jobs.

---

## 3. Three-Way Feature Matrix: Hermes vs Paperclip vs Factory for IG-88

| Workload Requirement | Hermes | Paperclip | Factory | Winner |
|---------------------|--------|-----------|---------|--------|
| Typed approval gates | ❌ No | ✅ Yes | ⚠️ FCT004 borrow | Paperclip → Factory |
| Cryptographic approval signing | ❌ No | ❌ DB-backed | ✅ HMAC-SHA256 | Factory |
| Per-agent budget hard stop | ❌ No | ✅ Yes | ⚠️ FCT004 borrow | Paperclip → Factory |
| Atomic task checkout | ❌ No | ✅ SQL atomic | ⚠️ FCT004 borrow | Paperclip → Factory |
| Deterministic event routing | ❌ Serverless/non-deterministic | ❌ Heartbeat (eventual) | ✅ Coordinator dispatch | Factory |
| Local MLX inference | ❌ External LLM only | ❌ External LLM only | ✅ Nanbeige4.1-3B | Factory |
| Market event latency | ❌ 2–5s cold start | ⚠️ 30s heartbeat minimum | ✅ 3s poll | Factory |
| E2EE transport | ❌ No | ❌ TLS only | ✅ Matrix Megolm | Factory |
| Temporal knowledge graph | ⚠️ FTS5 agent-local | ❌ No | ✅ Graphiti + Qdrant | Factory |
| Natural language scheduling | ✅ Yes | ❌ No | ❌ TOML only | Hermes |
| Multi-platform gateway | ✅ Yes | ❌ Single UI | ⚠️ Matrix only | Hermes |
| Autonomous skill creation | ✅ Yes | ❌ Static SKILLS.md | ❌ Static soul files | Hermes |
| Subagent orchestration | ✅ Python RPC | ❌ No delegation | ⚠️ Matrix-based | Hermes |
| Serverless hibernation | ✅ Daytona/Modal | ❌ Always-on | ❌ Always-on | Hermes |

**Factory wins**: 7 categories (approval cryptography, determinism, local inference, latency, E2EE, temporal KG, budget/task safety via FCT004)
**Hermes wins**: 4 categories (NL scheduling, multi-platform, skill creation, subagent RPC)
**Paperclip wins**: 0 independently (all Paperclip wins become Factory wins via FCT004 borrows)

---

## 4. Scheduling Model Comparison

### Hermes: Natural Language + Serverless Hibernation

```python
agent.schedule_task("every 3 hours, run deep_scan_skill")
agent.schedule_task("weekdays at 9:30am ET, check overnight news")
```

NL parser generates standard cron. Agent hibernates when idle (Daytona/Modal), wakes on timer expiry or incoming message. **Cold start: 2–5 seconds.**

### Paperclip: Fixed Heartbeat

Minimum 30s interval. Agent wakes, checks task queue, executes, sleeps. Events can trigger immediate wake. **Latency: 0–30s jitter.**

### Factory: Deterministic Polling + Timer.rs

```toml
[agent.ig88]
poll_interval_ms = 3000
```

```json
{
  "name": "deep_scan",
  "interval_secs": 10800,
  "next_fire": 1710769200,
  "enabled": true
}
```

Coordinator polls every 3s. Timer.rs state machine fires periodic tasks from JSON files. Deterministic — no race conditions, no cold start. **Mean latency: ~3.5s including dispatch overhead.**

**Verdict for IG-88:** Factory's 3s polling is correct. Serverless cold start (Hermes) is unacceptable for continuous market surveillance. Hermes's NL scheduling UX is the only genuine win — implementable as a Factory skill that parses natural language and compiles to timer JSON, without adopting the Hermes runtime.

---

## 5. Memory Model Comparison

### Hermes: Three-Tier (Inference → Skill Documents → Honcho)

- **Tier 1:** Short-term inference context
- **Tier 2:** Long-term Skill Documents (FTS5 full-text search, LLM-summarized workflows)
- **Tier 3:** Honcho user modeling (preferences, patterns, personalization)

Autonomous skill creation: on task completion, agent encodes the workflow as a retrievable Skill Document.

**For IG-88:** Dangerous. An auto-generated skill encoding a 2026-03-10 portfolio decision could propagate that logic to a 2026-03-17 context with entirely different market conditions. Human-curated skills are required for trading.

### Factory: Soul/Principles + Graphiti + Qdrant

- **Static layer:** Soul/principles files (identity, rules, constraints)
- **Temporal layer:** Graphiti knowledge graph (facts, relationships, causal history)
- **Semantic layer:** Qdrant vector search (cross-episode retrieval)

**For IG-88:** Superior to Hermes FTS5 because trading decisions are persistent — a Tesla decision from 2026-02-15 is still relevant on 2026-03-17. Graphiti survives agent restarts. Qdrant enables complex semantic queries ("all decisions involving energy sector in past 30 days").

### Honcho vs Graphiti

Not redundant — they answer different questions:
- **Honcho:** *How does the user prefer to receive information?*
- **Graphiti:** *What has the agent decided, and why, over time?*

For IG-88 (single-operator, execution-focused), Graphiti is sufficient. Honcho adds value only in multi-user or personalization-heavy contexts.

---

## 6. Architectural Tensions

### Python vs Rust

Hermes is Python. Factory coordinator-rs is Rust. Full integration options:

| Option | Approach | Cost | Latency |
|--------|----------|------|---------|
| Subprocess | Launch Hermes via Python subprocess, communicate via Matrix | High complexity | +500–2000ms/turn |
| Separate service | Run Hermes as HTTP service, coordinator calls it | Medium complexity | +network RTT |
| Skip runtime, borrow concept | Implement NL scheduler as Python skill within Factory task context | Low complexity | Negligible |

**Recommendation: Option C.** Hermes runtime is not the win. The NL scheduler concept is the win — implement it as a small Python skill within Factory's existing task infrastructure.

### Autonomous Skill Creation vs Human Curation

- **Hermes:** Agent encodes workflows autonomously as Skill Documents
- **Factory:** Human-curated soul/principles + Graphiti facts

For IG-88, autonomous skill creation is explicitly **not wanted**. Trading skills must be operator-reviewed. Implement explicit skill versioning in soul files instead:

```toml
[skills.portfolio_rebalance_v1]
author = "operator"
created = "2026-03-01"
approved_conditions = "market_open only"
sunset_date = "2026-06-01"
```

---

## 7. ADOPT / BORROW / LEARN / SKIP

### ADOPT: None

Hermes Agent runtime is incompatible with Factory's Rust/Matrix/deterministic architecture.

### BORROW

**Natural Language Task Scheduler (Priority: 6/10, Phase 2)**

Implement Hermes's NL scheduling concept as a Factory skill — a Python script that parses natural language task descriptions and compiles them to Timer.rs JSON files.

```python
# nl_scheduler.py (Factory skill, called from coordinator task context)
# Input: "Schedule deep scan every 3 hours starting Tuesday"
# Output: creates ~/.config/ig88/timers/deep_scan.json
def parse_nl_schedule(description: str) -> TimerSpec:
    # LLM call to parse description → structured cron spec
    # Returns: interval_secs, next_fire, enabled
    ...
```

This adds NL scheduling UX without adopting Hermes as a runtime.

### LEARN

- **Multi-level memory philosophy**: Hermes's three-tier approach (inference → procedural → user model) is architecturally sound. Factory's Graphiti + Qdrant already covers tiers 1 and 2. Consider whether a lightweight operator preference layer (analogous to Honcho) adds value for non-IG-88 agents (Kelk, Boot).
- **Subagent orchestration patterns**: Hermes's Python RPC model for isolated subagent conversations is cleaner than Factory's current Matrix-based delegation. Not actionable immediately, but worth noting for coordinator-rs v2 design.

### SKIP

- Hermes as primary agent runtime
- Hermes Financial Research Framework (research-only, not trading)
- Autonomous skill creation (unsafe for trading)
- Honcho user modeling (not needed for IG-88's single-operator model)
- Serverless hibernation (incompatible with continuous market surveillance)

---

## 8. Proposed Hybrid Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ IG-88 Trading System                                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Core: Factory Coordinator-rs                               │
│  ├── Deterministic event routing (Matrix)                   │
│  ├── HMAC-signed approval gates                             │
│  └── Local MLX inference (Nanbeige4.1-3B, 256K ctx)        │
│                                                             │
│  From Paperclip (FCT004 borrows):                           │
│  ├── task_lease.rs — atomic task checkout                   │
│  ├── ApprovalGateType enum — typed gates (5 types)          │
│  ├── budget.rs — per-agent monthly limits + hard pause      │
│  └── ContextMode enum — Thin vs Fat context routing         │
│                                                             │
│  From Hermes (concepts only, not runtime):                  │
│  └── nl_scheduler.py skill — NL → Timer.rs JSON (Phase 2)  │
│                                                             │
│  Factory-unique:                                            │
│  ├── Graphiti temporal KG (trading decision history)        │
│  ├── Qdrant semantic search                                 │
│  ├── Matrix E2EE (Megolm audit trail)                       │
│  └── Circuit breaker degradation (L1–L4)                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Trading Execution Flow

1. IG-88 detects market signal via scanner (Factory Matrix message, 3s poll)
2. IG-88 drafts `TradingExecution` approval request (typed gate, Paperclip borrow #2)
3. Operator approves in Element with 5-minute timeout
4. Coordinator-rs checks budget before dispatch (Paperclip borrow #3)
5. IG-88 places trade, encodes decision to Graphiti
6. Subsequent trades query Graphiti: "What have I done with TSLA in the past 7 days?"

### Budget Governance Flow

1. IG-88 runs 50 inferences at ~$0.001/ea against $500 monthly limit
2. At 80% ($400): coordinator posts warning to STATUS_ROOM
3. At 100% ($500): coordinator auto-pauses IG-88, requires `BudgetOverride` typed approval (1-hour timeout)
4. Operator approves override, limit increases

---

## 9. Implementation Roadmap

**Phase 1 — FCT004 implementation (Weeks 1–2, already planned):**
- `task_lease.rs` — atomic task checkout
- Typed `ApprovalGateType` in `approval.rs`
- `budget.rs` — per-agent monthly limits
- `ContextMode` enum in `agent.rs`

**Phase 2 — Hermes concept (Week 4+, optional):**
- `nl_scheduler.py` skill — NL → Timer.rs JSON
- Operator writes "every 3h deep scan" → coordinator creates timer file
- Low priority; TOML-based scheduling is adequate

**Phase 3 — Graphiti enhancement (later):**
- Trading-specific temporal queries
- Aggregation: "largest position by notional", "P&L by sector past 30 days"
- Cross-episode pattern detection

**Skip entirely:**
- Hermes runtime adoption
- Hermes Financial Framework
- Autonomous skill creation
- Honcho user modeling

---

## 10. Verdict: Is Hermes a Better Fit for IG-88 Than Paperclip?

**No.**

Paperclip has three primitives that IG-88 needs right now: typed approval gates, budget hard stops, and atomic task checkout. Hermes has none of these. Hermes's wins (NL scheduling, multi-platform gateway, autonomous skill creation) are nice-to-haves or actively undesirable in a trading context.

The correct stack is **Factory + Paperclip borrows (FCT004)**. Hermes contributes one borrowable concept (NL scheduler) for Phase 2. Everything else in Hermes is either mismatched to IG-88's requirements or already done better by Factory.

---

## References

[1] Nous Research, "Hermes Agent," GitHub. [Online]. Available: https://github.com/NousResearch/hermes-agent

[2] J. Schnetzler, "Hermes Financial Research Framework," GitHub. [Online]. Available: https://github.com/schnetzlerjoe/hermes

[3] FCT004, "Paperclip vs Factory — Architecture Study and Adoption Assessment," Factory planning repo, 2026-03-17.

[4] FCT002, "Factory Agent Architecture — Roles, Models, and Autonomous Loop Design," Factory planning repo.

[5] Hermes Agent Architecture Documentation. [Online]. Available: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture/

[6] Hermes Agent Skills System. [Online]. Available: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/
