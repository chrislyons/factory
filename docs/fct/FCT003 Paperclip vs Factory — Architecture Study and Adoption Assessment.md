# FCT003 Paperclip vs Factory — Architecture Study and Adoption Assessment

**Date:** 2026-03-17
**Authors:** 5-agent research team
**Status:** Final — Adoption recommendation approved

---

## 1. Executive Summary

Paperclip (paperclip.ing) is an open-source MIT-licensed orchestration platform for autonomous "zero-human companies." Its stack is Node.js/TypeScript + Express REST API + PostgreSQL (Drizzle ORM) + React UI. Factory's coordinator-rs is a Rust binary with deterministic routing, Matrix protocol substrate, and HMAC-signed approvals.

The two systems have complementary strengths. Factory excels at local inference, hybrid memory, and cryptographic governance. Paperclip excels at budget enforcement, org hierarchy, and atomic task coordination.

**Recommendation: BORROW 3 patterns. Do NOT adopt Paperclip wholesale.**

Priority borrows:
1. Atomic task checkout — prevents double-claiming in concurrent agent queues
2. Typed approval gates — adds semantic gate types to Factory's untyped HMAC system
3. Per-agent budget tracking — hard kill switches for inference cost control

---

## 2. Paperclip Platform Overview

**Sources:** https://paperclip.ing/docs | https://github.com/paperclipai/paperclip

### Core Stack

- Node.js/TypeScript + Express REST API
- PostgreSQL with Drizzle ORM (type-safe schema migrations)
- React frontend UI for operator oversight
- MIT licensed, self-hostable

### Key Entities

**Company** — Top-level unit. Contains an org chart, board, CEO agent, and monthly budget envelope. All agents operate within a Company context.

**Heartbeat** — Scheduling primitive. Minimum 30-second interval. Agents wake on heartbeat, inspect their task queue, execute work, then sleep. No polling, no event-driven push.

**Task** — Atomic unit of work. Checkout is a single SQL `UPDATE ... WHERE claimed_by IS NULL` — any concurrent claim returns HTTP 409. This prevents double-assignment at the database level without distributed locks.

**Board** — Governance layer. Approval gates for strategic decisions, agent hiring, budget overrides, and tool calls. Structured as a first-class architectural component, not a policy layer.

### Key Source Files (from GitHub analysis)

| File | Size | Role |
|------|------|------|
| `heartbeat.ts` | 108KB | Core scheduling loop |
| `budgets.ts` | 31KB | Per-agent budget tracking |
| `issues.ts` | 49KB | Task/issue lifecycle management |
| `approvals.ts` | 9KB | Approval gate system |
| `plugins/` (27 files) | — | External service adapters |

### 10 Novel Design Patterns Identified

1. **Heartbeat scheduling** — periodic wake cycles (not polling, not event-driven)
2. **Atomic task checkout** — single SQL UPDATE + 409 conflict response
3. **Per-agent monthly budget** — 80% warn / 100% hard pause thresholds
4. **Board governance as structural layer** — not ad-hoc, built into architecture
5. **Typed approval gates** — `ToolCall`, `HireAgent`, `StrategicDecision`, `BudgetOverride`
6. **SKILLS.md runtime injection** — agents receive capability manifests at startup
7. **Thin vs Fat context modes** — minimal vs full context for task complexity routing
8. **Portable company templates** — export entire org as a replayable bootstrap template
9. **Single-operator framing** — one human owns a company of agents (UX-level constraint)
10. **Plugin ecosystem** — 27 standardized service adapters with uniform interface

---

## 3. Factory vs Paperclip Feature Parity Matrix

| Feature | Factory (coordinator-rs) | Paperclip | Gap |
|---------|--------------------------|-----------|-----|
| Scheduling | timer.rs (10s JSON poll) | Heartbeat (30s min, DB-backed) | Factory: file-based, less resilient |
| Task routing | Deterministic Rust dispatch | DB-backed queue with atomic checkout | Factory: no atomic claim |
| Approval gates | HMAC-signed approvals (untyped) | Typed gates (ToolCall, HireAgent, etc.) | Factory: no gate types |
| Budget tracking | None | Per-agent monthly (80% warn, 100% pause) | Factory: missing |
| Memory | Graphiti + Qdrant + FalkorDB | In-DB activity log (append-only) | Paperclip: simpler, Factory: richer |
| Agent identity | soul/ + principles/ files | SKILLS.md injection | Both valid, different philosophy |
| Context modes | None | Thin / Fat modes | Factory: missing |
| Governance | Loop Spec + ATR002 frozen harness | Board voting + approval gates | Both strong, different mechanisms |
| Inference | Local MLX models (Nanbeige, Qwen, LFM) | External API calls only | Factory: major advantage |
| Protocol substrate | Matrix (E2EE, federated) | REST + WebSockets | Factory: major advantage |
| Model tiers | L2/L3 role-based (4 models) | Homogeneous (any LLM) | Factory: advantage |
| Hybrid memory | Graphiti temporal KG + Qdrant vector | None | Factory: major advantage |
| Company portability | None | Full org export as template | Paperclip: unique |
| Org hierarchy | Flat (coordinator + agents) | CEO → Reports → Board | Paperclip: richer |
| Plugin system | None formalized | 27 service adapters | Paperclip: advantage |
| Loop governance | ATR002 auto-reject rules | Board approval for loops | Both adequate |
| Conflict prevention | None | Atomic SQL checkout | Factory: gap |
| Cost control | None | Hard budget kill switch | Factory: gap |

---

## 4. Research Vault Verification

Twenty Qdrant searches were run against projects-vault to identify overlap with prior research.

**Confirmed overlaps:**

| Qdrant Record | Finding |
|---------------|---------|
| TX260217_0000-T9L6 | Heartbeat scheduling — matches prior research on agentic scheduling primitives |
| TX260217_1650-D994 | "Zero-human company" framing — consistent with Factory's long-term operational goals |
| TX260219_1637-5ED2 | SKILLS.md capability manifest injection — previously studied pattern |
| TX260226_0000-0670 | OpenClaw — task checkout conflict prevention referenced in prior work |

**Genuinely new territory (not previously in vault):**

1. Atomic task checkout as a formalized pattern — single SQL UPDATE + 409, no distributed lock required
2. Hard budget kill switches — not monitoring-only, actual pause enforcement at the dispatch layer
3. Board governance as a structural architectural layer — not a policy overlay, built into entity model
4. "Company-as-a-service" product framing — portable org templates for bootstrapping autonomous companies

---

## 5. ADOPT / BORROW / LEARN / SKIP Analysis

### ADOPT: Rejected

Full adoption is not viable for the following reasons:

- **Stack mismatch**: Paperclip is Node.js/TypeScript + PostgreSQL. Factory is Rust + TOML + binary coordinator.
- **Data model incompatibility**: Paperclip's Company/Org hierarchy does not map to Factory's flat coordinator + agent model. A migration would require redesigning coordinator-rs from scratch.
- **Substrate conflict**: Paperclip uses REST + WebSockets. Factory uses Matrix (E2EE, federated). Transports are incompatible at the protocol level.
- **Governance regression**: Factory's HMAC-signed approvals and ATR002 frozen harness provide cryptographic guarantees that Paperclip's board voting cannot replicate.
- **Inference regression**: Factory runs local MLX models (Nanbeige, Qwen, LFM). Paperclip assumes external API calls only. Wholesale adoption would eliminate Factory's cost and latency advantages.

### BORROW (Priority Order)

---

#### #1 — Atomic Task Checkout → `task_lease.rs`

**Priority: 9/10 | Timeline: Week 1**

**Problem:** Factory has no protection against two agents simultaneously claiming the same task. Under concurrent load (e.g., IG-88 and Boot both receiving a routed task), double-claiming is possible and would produce duplicate actions.

**Paperclip solution:** Single SQL `UPDATE` with conditional `WHERE claimed_by IS NULL`. If the row is already claimed, the UPDATE affects 0 rows and returns HTTP 409.

**Factory adaptation:** In-memory lease manager in coordinator-rs using `tokio::sync::Mutex`. No database required — coordinator already serializes dispatch.

```rust
// src/coordinator-rs/src/task_lease.rs
use std::collections::HashMap;
use tokio::sync::Mutex;
use std::time::{SystemTime, Duration};

pub struct TaskLease {
    pub agent_id: String,
    pub claimed_at: SystemTime,
    pub lease_duration: Duration,
}

pub struct TaskLeaseManager {
    leases: Mutex<HashMap<String, TaskLease>>,
}

impl TaskLeaseManager {
    pub async fn try_claim(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> {
        let mut leases = self.leases.lock().await;
        if let Some(existing) = leases.get(task_id) {
            if !existing.is_expired() {
                return Err(LeaseError::AlreadyClaimed);
            }
        }
        leases.insert(task_id.to_string(), TaskLease::new(agent_id));
        Ok(())
    }

    pub async fn renew_lease(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> { ... }
    pub async fn release_lease(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> { ... }
    pub async fn cleanup_expired(&self) { ... }
}
```

---

#### #2 — Typed Approval Gates → extend `approval.rs`

**Priority: 8.5/10 | Timeline: Weeks 1-2**

**Problem:** Factory's HMAC approval system has no semantic gate types. All approvals are structurally identical — a `LoopSpecDeploy` and a `ToolCall` go through the same path with the same timeout behavior. This makes it impossible to set differential timeout policies or auto-approval rules.

**Paperclip solution:** `ApprovalGateType` enum with distinct handling per type.

**Factory adaptation:** Add enum to `approval.rs`, add policy methods, wire into dispatch.

```rust
// Extend src/coordinator-rs/src/approval.rs
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ApprovalGateType {
    ToolCall,
    TradingExecution,
    AgentElevation,
    LoopSpecDeploy,
    BudgetOverride,
}

pub struct ApprovalRequest {
    pub gate_type: ApprovalGateType,
    pub agent_id: String,
    pub payload: serde_json::Value,
    pub requested_at: SystemTime,
}

pub struct ApprovalGatePolicies;

impl ApprovalGatePolicies {
    pub fn can_auto_approve(gate: &ApprovalGateType) -> bool {
        matches!(gate, ApprovalGateType::ToolCall)
    }

    pub fn approval_timeout_ms(gate: &ApprovalGateType) -> u64 {
        match gate {
            ApprovalGateType::LoopSpecDeploy   => 3_600_000,  // 1 hour
            ApprovalGateType::TradingExecution => 300_000,    // 5 min
            ApprovalGateType::BudgetOverride   => 86_400_000, // 24 hours
            _                                  => 60_000,     // 1 min default
        }
    }
}
```

---

#### #3 — Per-Agent Budget Tracking → new `budget.rs`

**Priority: 7.5/10 | Timeline: Week 2**

**Problem:** Factory has no cost controls. IG-88 runs inference on every trading cycle with no visibility into monthly spend. A runaway loop or bad LoopSpec could burn significant API budget before a human notices.

**Paperclip solution:** Per-agent monthly budget with 80% warning threshold and 100% hard pause. Budget is deducted at the point of inference dispatch.

**Factory adaptation:** New `budget.rs` module. Budget limits defined in `coordinator.toml`. Deduction called from agent message dispatch path.

```rust
// src/coordinator-rs/src/budget.rs
#[derive(Debug, Clone)]
pub enum BudgetStatus {
    Normal,
    Warning { usage_pct: f64 },
    Paused { reason: String },
}

pub struct AgentBudget {
    pub agent_id: String,
    pub monthly_limit_usd: f64,
    pub spent_this_month_usd: f64,
}

pub struct BudgetTracker {
    budgets: Mutex<HashMap<String, AgentBudget>>,
}

impl BudgetTracker {
    pub async fn deduct_and_check(&self, agent_id: &str, cost: f64) -> BudgetStatus {
        let mut budgets = self.budgets.lock().await;
        let budget = budgets.get_mut(agent_id).unwrap();
        budget.spent_this_month_usd += cost;
        let pct = budget.spent_this_month_usd / budget.monthly_limit_usd;
        match pct {
            p if p >= 1.0 => BudgetStatus::Paused { reason: "Monthly limit reached".into() },
            p if p >= 0.8 => BudgetStatus::Warning { usage_pct: p },
            _             => BudgetStatus::Normal,
        }
    }
}
```

TOML config pattern:
```toml
[budget.ig88]
monthly_limit_usd = 500.0

[budget.boot]
monthly_limit_usd = 100.0
```

---

### LEARN (adapt philosophy, not code)

**Goal hierarchy cascading** — Paperclip propagates goals from CEO → department → individual agent. Factory could benefit from explicit goal chains rather than implicit coordinator routing. No code to borrow, but the mental model is worth formalizing in Loop Spec design.

**Single-operator framing** — Paperclip's UX is built around one human owning a company of agents. Factory is currently diffuse in its operator model. Tightening the "one operator, many agents" mental model would improve tooling focus and reduce ambiguity in approval routing.

### SKIP

| Pattern | Reason |
|---------|--------|
| Org chart hierarchy (Company/CEO/Department) | Incompatible with Factory's flat coordinator model |
| Board voting (quorum logic) | Factory's ATR002 + Loop Spec already handles governance more deterministically |
| Company portability / export templates | Not relevant to Factory's single-deployment model |
| Multi-agent hiring workflows | Factory uses manual agent instantiation |

---

## 6. Implementation Roadmap

### Week 1

- [ ] Create `src/coordinator-rs/src/task_lease.rs` — `TaskLeaseManager` with `try_claim`, `renew`, `release`, `cleanup_expired`
- [ ] Integrate `task_lease` into coordinator dispatch loop (wrap existing task routing)
- [ ] Add `ApprovalGateType` enum to `approval.rs`
- [ ] Add `ApprovalGatePolicies` with `can_auto_approve()` and `approval_timeout_ms()`

### Week 2

- [ ] Create `src/coordinator-rs/src/budget.rs` — `BudgetTracker` + `AgentBudget` + `BudgetStatus`
- [ ] Add budget config block to `coordinator.toml` (per-agent monthly limits for ig88, boot, kelk)
- [ ] Wire `deduct_and_check()` into agent message dispatch path
- [ ] Add `ContextMode` enum to `agent.rs` (Thin/Fat) for future context routing

### Success Metrics

- Zero double-claim incidents in IG-88 task queue under concurrent dispatch tests
- IG-88 budget usage visible in coordinator logs at each inference call
- `LoopSpecDeploy` approval requests enforce 1-hour timeout with no auto-approve path

---

## 7. Conclusions

Paperclip is a well-engineered orchestration platform solving the same problem space from a different angle. The two systems reflect different constraints: Paperclip optimizes for human readability, org hierarchy, and cost transparency; Factory optimizes for determinism, cryptographic integrity, and local inference.

Factory should not abandon its architectural advantages — local MLX inference, Matrix E2EE substrate, Graphiti temporal memory, HMAC-signed approvals — to adopt Paperclip wholesale. The migration cost would be total and the regression in security and inference capability would be severe.

However, Paperclip has solved three concrete coordination problems that Factory has not addressed: concurrent task claiming, typed approval semantics, and per-agent cost enforcement. These are bounded, tractable additions to coordinator-rs that map cleanly to existing module boundaries. They carry no architectural risk and directly address operational gaps that become more significant as IG-88's trading workloads scale.

The borrow list is the right output of this study.

---

## References

[1] Paperclip platform documentation. https://paperclip.ing/docs. Accessed 2026-03-17.
[2] Paperclip source repository. https://github.com/paperclipai/paperclip. Accessed 2026-03-17.
