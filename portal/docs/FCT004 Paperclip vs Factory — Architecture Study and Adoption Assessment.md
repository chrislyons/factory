# FCT004 Paperclip vs Factory — Architecture Study and Adoption Assessment

**Prefix:** FCT
**Repo:** `~/dev/factory/`
**Date:** 2026-03-17
**Authors:** 4-agent research team (docs study, GitHub source analysis, infrastructure comparison, adoption assessment)
**Status:** Final — ready for implementation
**Related:** FCT001, FCT002, FCT003, BKX074, ATR002

---

## 1. Executive Summary

Paperclip (paperclip.ing) is an open-source MIT-licensed orchestration platform for autonomous "zero-human companies." Its stack is Node.js/TypeScript + Express REST API + PostgreSQL (Drizzle ORM) + React UI. Factory's coordinator-rs is a Rust binary with deterministic routing, Matrix E2EE protocol substrate, HMAC-signed approvals, and local MLX inference.

The two systems have complementary strengths. Factory excels at local inference, hybrid memory, cryptographic governance, and E2EE transport. Paperclip excels at budget enforcement, org hierarchy, atomic task coordination, and structured governance.

**Recommendation: BORROW 4 patterns. Do NOT adopt Paperclip wholesale.**

Priority borrows (in order):
1. Atomic task checkout — `task_lease.rs` — prevents double-claiming in concurrent agent queues (Priority 9/10)
2. Typed approval gates — extend `approval.rs` — adds semantic gate types and differential timeout policies (Priority 8.5/10)
3. Per-agent budget tracking — new `budget.rs` — hard kill switches for inference cost control (Priority 7.5/10)
4. Context mode (Thin/Fat) — extend `agent.rs` — routes task complexity to appropriate context depth (Priority 6/10)

---

## 2. Paperclip Platform Overview

**Sources:** https://paperclip.ing/docs [1] | https://github.com/paperclipai/paperclip [2]

### Core Stack

- Node.js/TypeScript + Express v5.1.0
- PostgreSQL via Drizzle ORM 0.38.4 (type-safe schema migrations)
- React/Vite frontend UI for operator oversight
- better-auth JWT, pino logging, Zod validation
- MIT licensed, self-hostable, Docker supported
- Version 0.3.1

### Repo Structure

```
paperclip/
├── server/              # Express REST API + orchestration (26KB index.ts)
├── ui/                  # React + Vite frontend
├── packages/
│   ├── db/              # Drizzle ORM schema, migrations, DB client
│   ├── shared/          # Shared types, validators, API constants
│   ├── adapters/        # Agent adapters (Claude, Codex, Cursor, OpenClaw, etc.)
│   ├── plugins/         # Plugin SDK + examples
│   └── adapter-utils/   # Shared adapter utilities
├── skills/              # Shared skill definitions
└── doc/                 # SPEC.md, SPEC-implementation.md, DATABASE.md
```

### Key Source Files

| File | Size | Role |
|------|------|------|
| `server/src/services/heartbeat.ts` | 108.5KB | Core scheduling loop [3] |
| `server/src/services/issues.ts` | 53.4KB | Task lifecycle management [6] |
| `server/src/services/budgets.ts` | 31.7KB | Per-agent budget enforcement [4] |
| `server/src/services/approvals.ts` | 9.1KB | Approval gate system [5] |

### Five Core Entities

**Company** — top-level boundary; complete data isolation; contains Org Chart, Goals, Agents, Budgets, Tickets. Every table is scoped by `companyId`.

**Org Chart** — hierarchical agent structure (CEO, CTO, CMO, etc.) with reporting lines and formal roles.

**Agent** — autonomous worker (Claude Code, OpenClaw, bash, HTTP); has role, boss, title, job description, monthly budget.

**Goal** — 4-level hierarchy: Mission → Project Goal → Agent Goal → Task. Every task carries full goal ancestry so agents always know the "why."

**Ticket** — work unit + append-only audit trail with full tool-call tracing. Stored in `issues` table with atomic checkout guard.

### Scheduling Model

Heartbeat scheduling: customizable per-agent wake cycles (4h, 8h, 12h). Minimum 30-second interval. Agents wake, check queue, execute, sleep. Also event-triggered (issue assigned, mention, delegation). `heartbeatRuns` table logs every wake: status `queued→started→finished`, `contextSnapshot` JSONB, `logRef` S3, invocationSource (`on_demand|scheduled|event`).

### Deployment

Self-hosted. `npx paperclipai onboard --yes` for local setup. Embedded PostgreSQL for local dev, external PostgreSQL for production. Multi-company isolation via `companyId` scoping on every query.

### 10 Novel Design Patterns

1. **Heartbeat scheduling** — periodic wake cycles, not polling, not always-on
2. **Atomic task checkout** — single SQL UPDATE WHERE `checkoutRunId IS NULL`; HTTP 409 on conflict
3. **Per-agent monthly budget** — 80% warn / 100% hard pause with board override path
4. **Board governance as structural layer** — first-class entity, not a policy overlay
5. **Typed approval gates** — `hire_agent`, `budget_override_required` with status flow
6. **SKILLS.md runtime injection** — capability manifests at startup, no model retraining
7. **Goal ancestry context injection** — 4-level hierarchy into every task dispatch
8. **Persistent session state across heartbeats** — `agentTaskSessions` unique index on `(companyId, agentId, adapterType, taskKey)`
9. **Multi-company single deployment** — `companyId` scoping with complete isolation
10. **Unopinionated agent adapter model** — Claude Code, OpenClaw, bash, HTTP, webhooks

---

## 3. Factory vs Paperclip Feature Parity Matrix

Factory infrastructure sourced from direct read of coordinator-rs source:
- `POLL_INTERVAL_MS=3000`, `APPROVAL_SWEEP_INTERVAL_MS=60000`, `TIMER_CHECK_INTERVAL_SECS=10`
- `OUTPUT_DEDUP_BUFFER_SIZE=20`, `OUTPUT_DEDUP_WINDOW_SECS=60`
- `AgentConfig` struct has no budget field
- `approval.rs`: HMAC-SHA256, `ApprovalRecord`, `ApprovalDecision` enum (Approved/Rejected/TimedOut), file-based, `ApprovalRateLimiter` (max 5/agent/60s), no typed gate types
- `agent.rs`: `UserMessage` struct (role, content, content_blocks, room_id, event_id), no `ContextMode` enum
- `timer.rs`: file-based JSON in `~/.config/ig88/timers/`, moves to `.fired` on execution
- `lifecycle.rs`: circuit breaker (`BreakerAction` enum: Pause/Kill/None), flap suppression 2 consecutive failures, trust levels L1-L4

| # | Feature | Factory | Paperclip | Gap | Priority |
|---|---------|---------|-----------|-----|----------|
| 1 | Multi-instance concurrency safety | Circuit breaker (heuristic) | Atomic SQL checkout | CRITICAL | P0 |
| 2 | Budget enforcement — soft limit | None | 80% → warning | CRITICAL | P0 |
| 3 | Budget enforcement — hard limit | None | 100% → auto-pause | CRITICAL | P0 |
| 4 | Cost per-invocation tracking | None | `costEvents` table | CRITICAL | P0 |
| 5 | Mandatory approval gates | Optional (whitelist) | `hire_agent`, `budget_override_required` | CRITICAL | P0 |
| 6 | Approval workflow — threaded discussion | Binary emoji | `ApprovalComments` thread | IMPORTANT | P1 |
| 7 | Approval automation — enforcement | None (observer only) | Auto-blocks action | IMPORTANT | P1 |
| 8 | Approval typing system | Implicit (1 type) | Typed (2+, extensible) | IMPORTANT | P1 |
| 9 | Heartbeat persistence | Filesystem JSON | `heartbeatRuns` table | IMPORTANT | P1 |
| 10 | Governance board structure | None | First-class Board entity | IMPORTANT | P1 |
| 11 | Multi-turn session carryover | 3000 chars (weak) | `agentTaskSessions` (strong) | IMPORTANT | P1 |
| 12 | Goal context injection | None | 4-level goal ancestry | IMPORTANT | P1 |
| 13 | Skill runtime adaptation | None (static) | Goal-based SKILLS.md | IMPORTANT | P1 |
| 14 | Audit trail queryability | Flat files | SQL (structured) | IMPORTANT | P1 |
| 15 | Task state machine (checkout→execute) | None | `issues` table (3-state) | IMPORTANT | P1 |
| 16 | Plugin ecosystem | None (static whitelist) | 30+ plugins + SDK | IMPORTANT | P1 |
| 17 | Temporal knowledge graph | Graphiti (yes) | No | MINOR | P2 |
| 18 | Semantic vector search | Qdrant (yes) | No | MINOR | P2 |
| 19 | E2EE transport | Matrix Megolm | TLS only | MINOR | P2 |
| 20 | Approval HMAC signing | Yes (file-based) | Database-backed | MINOR | P2 |
| 21 | Circuit breaker degradation | Yes (L1-L4) | No | MINOR | P2 |
| 22 | Per-agent filesystem memory | Yes (priority-tagged facts) | No | MINOR | P2 |
| 23 | Request/response sync semantics | No (async Matrix) | REST (sync) | MINOR | P2 |
| 24 | Multi-company isolation | No (single cluster) | `companyId` scoping | MINOR | P2 |

---

## 4. ADOPT Verdict — Full Reasoning

**Recommendation: NO. Do not adopt Paperclip wholesale.**

### Stack Incompatibility

Factory is a Rust binary (~6,677 lines) with tokio async. Paperclip is Node.js/TypeScript + Express. A full migration would require complete rewrites of: the dispatch loop (coordinator.rs, ~1,200 lines), the approval pipeline (approval.rs + lifecycle.rs, ~800 lines), the agent subprocess I/O (agent.rs, ~1,000 lines), and the Matrix protocol layer (~900 lines). Estimated migration cost: 16–20 weeks of engineering with high regression risk.

### Data Model Incompatibility

Paperclip's Company → CEO → Departments → Agents relational hierarchy has no mapping to Factory's flat coordinator + agent roster with deterministic routing. `AgentConfig` has no hierarchy field, no budget field. A migration would require architectural redesign of the config schema and routing model, not just code translation.

### Protocol Substrate Conflict

Paperclip uses REST + WebSocket. Factory uses Matrix E2EE (Megolm AES-256, federated, DAG event ordering). HTTP request/response cycles are incompatible with Matrix event streaming (sync_token-based pagination). Pantalaimon proxy for E2EE adds a layer Paperclip's architecture has no concept of.

### Governance Regression

Factory's HMAC-SHA256 approval signatures provide cryptographic proof of decisions — a human signed this approval at this timestamp. Paperclip's database-backed approvals are auditable but not cryptographically signed. Wholesale adoption would eliminate this guarantee.

### Inference Regression

Paperclip assumes external LLM API calls only. Factory runs local MLX models (Nanbeige4.1-3B, Qwen3.5-4B, LFM2.5-1.2B) with zero marginal cost per inference. Wholesale adoption would eliminate Factory's cost and latency advantages and introduce dependency on external API availability.

---

## 5. BORROW Analysis

### Borrow #1 — Atomic Task Checkout → `task_lease.rs`

**Priority: 9/10 | Timeline: Week 1**

**Problem:** Factory has no protection against two agents simultaneously claiming the same task. Under concurrent dispatch (e.g., IG-88 and Boot both receiving a routed task), double-claiming is possible and produces duplicate actions. The circuit breaker state is not serializable and does not prevent this at the dispatch level.

**Paperclip's solution:**
```typescript
.where(and(eq(issues.id, issueId), isNull(issues.checkoutRunId), isNull(issues.executionRunId)))
// If no rows updated → throws conflict("Issue already checked out")
```

**Factory adaptation:** In-memory lease manager in coordinator-rs using `tokio::sync::Mutex`. No database required — coordinator already serializes dispatch. 5-minute TTL handles orphaned leases from crashed agents.

```rust
// src/coordinator-rs/src/task_lease.rs
use std::collections::HashMap;
use std::time::{Duration, SystemTime};
use tokio::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LeaseError {
    #[error("Task {0} already claimed by agent {1}")]
    AlreadyClaimed(String, String),
    #[error("Task {0} not found or not owned by agent {1}")]
    NotOwned(String, String),
}

#[derive(Debug, Clone)]
pub struct TaskLease {
    pub agent_id: String,
    pub claimed_at: SystemTime,
    pub lease_duration: Duration,
}

impl TaskLease {
    pub fn new(agent_id: &str) -> Self {
        Self {
            agent_id: agent_id.to_string(),
            claimed_at: SystemTime::now(),
            lease_duration: Duration::from_secs(300), // 5-min default
        }
    }

    pub fn is_expired(&self) -> bool {
        SystemTime::now()
            .duration_since(self.claimed_at)
            .map(|d| d > self.lease_duration)
            .unwrap_or(true)
    }
}

pub struct TaskLeaseManager {
    leases: Mutex<HashMap<String, TaskLease>>,
}

impl TaskLeaseManager {
    pub fn new() -> Self {
        Self { leases: Mutex::new(HashMap::new()) }
    }

    pub async fn try_claim(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> {
        let mut leases = self.leases.lock().await;
        if let Some(existing) = leases.get(task_id) {
            if !existing.is_expired() {
                return Err(LeaseError::AlreadyClaimed(
                    task_id.to_string(),
                    existing.agent_id.clone(),
                ));
            }
        }
        leases.insert(task_id.to_string(), TaskLease::new(agent_id));
        Ok(())
    }

    pub async fn renew_lease(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> {
        let mut leases = self.leases.lock().await;
        match leases.get_mut(task_id) {
            Some(lease) if lease.agent_id == agent_id => {
                lease.claimed_at = SystemTime::now();
                Ok(())
            }
            _ => Err(LeaseError::NotOwned(task_id.to_string(), agent_id.to_string())),
        }
    }

    pub async fn release_lease(&self, task_id: &str, agent_id: &str) -> Result<(), LeaseError> {
        let mut leases = self.leases.lock().await;
        match leases.get(task_id) {
            Some(lease) if lease.agent_id == agent_id => {
                leases.remove(task_id);
                Ok(())
            }
            _ => Err(LeaseError::NotOwned(task_id.to_string(), agent_id.to_string())),
        }
    }

    pub async fn cleanup_expired(&self) {
        let mut leases = self.leases.lock().await;
        leases.retain(|_, lease| !lease.is_expired());
    }

    pub async fn active_count(&self) -> usize {
        let leases = self.leases.lock().await;
        leases.values().filter(|l| !l.is_expired()).count()
    }
}
```

Integration in coordinator.rs dispatch loop:
```rust
// In coordinator state:
task_lease_manager: Arc<TaskLeaseManager>,

// In dispatch_to_agent(), before routing:
if let Err(e) = self.task_lease_manager.try_claim(&task_id, &agent_id).await {
    warn!("Task {} already claimed, skipping dispatch: {}", task_id, e);
    return Ok(());
}
// On agent completion or error:
self.task_lease_manager.release_lease(&task_id, &agent_id).await.ok();

// In maintenance loop (every 60s):
self.task_lease_manager.cleanup_expired().await;
```

---

### Borrow #2 — Typed Approval Gates → extend `approval.rs`

**Priority: 8.5/10 | Timeline: Weeks 1–2**

**Problem:** Factory's HMAC approval system has no semantic gate types. All approvals are structurally identical — a `LoopSpecDeploy` and a `ToolCall` go through the same path with the same timeout behavior. This makes differential timeout policies and auto-approval rules impossible.

**Paperclip's solution:** `hire_agent` and `budget_override_required` approval types with distinct handling per type and status flow: `pending → approved | rejected | revision_requested → resubmit → pending`.

**Factory adaptation:** Add `ApprovalGateType` enum and `ApprovalGatePolicies` to `approval.rs`. Wire into dispatch guard. Preserve existing HMAC signing — types layer on top, not replacing the signing mechanism.

```rust
// Extend src/coordinator-rs/src/approval.rs

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ApprovalGateType {
    ToolCall,            // Standard MCP tool execution
    TradingExecution,    // IG-88 trade placement
    AgentElevation,      // Trust level promotion (L3 → L4)
    LoopSpecDeploy,      // Autonomous loop activation
    BudgetOverride,      // Manual monthly limit increase
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApprovalRequest {
    pub id: String,
    pub gate_type: ApprovalGateType,
    pub agent_id: String,
    pub payload: serde_json::Value,
    pub requested_at: SystemTime,
}

pub struct ApprovalGatePolicies;

impl ApprovalGatePolicies {
    /// Whether the gate type can be auto-approved without human input.
    pub fn can_auto_approve(gate: &ApprovalGateType) -> bool {
        matches!(gate, ApprovalGateType::ToolCall)
    }

    /// Timeout in milliseconds before the approval is auto-rejected.
    pub fn approval_timeout_ms(gate: &ApprovalGateType) -> u64 {
        match gate {
            ApprovalGateType::LoopSpecDeploy   => 3_600_000,   // 1 hour
            ApprovalGateType::TradingExecution => 300_000,     // 5 minutes
            ApprovalGateType::BudgetOverride   => 86_400_000,  // 24 hours
            ApprovalGateType::AgentElevation   => 3_600_000,   // 1 hour
            ApprovalGateType::ToolCall         => 60_000,      // 1 minute
        }
    }

    /// Whether a missing or timed-out approval blocks dispatch entirely.
    pub fn is_blocking(gate: &ApprovalGateType) -> bool {
        !matches!(gate, ApprovalGateType::ToolCall)
    }
}
```

Backward compatibility: add `#[serde(default)]` to `gate_type` on existing `ApprovalRecord` so old approval files deserialize cleanly.

---

### Borrow #3 — Per-Agent Budget Tracking → new `budget.rs`

**Priority: 7.5/10 | Timeline: Week 2**

**Problem:** Factory has zero cost accounting. IG-88 runs inference on every trading cycle with no visibility into monthly spend. A runaway loop or bad LoopSpec could burn significant API budget before a human notices.

**Paperclip's solution:**
```typescript
// budgetPolicies: scopeType, amount (cents), warnPercent: 80, hardStopEnabled
// Hard stop: agents.status = "paused", pauseReason = "budget"
// Pre-invocation: getInvocationBlock() cascades company → agent → project
```

**Factory adaptation:** New `budget.rs` module. Per-agent limits in `coordinator.toml`. `deduct_and_check()` called before each inference dispatch. `BudgetStatus::Paused` blocks dispatch and posts warning to Matrix monitoring room.

```rust
// src/coordinator-rs/src/budget.rs
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq)]
pub enum BudgetStatus {
    Normal,
    Warning { usage_pct: f64 },
    Paused { reason: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentBudget {
    pub agent_id: String,
    pub monthly_limit_usd: f64,
    pub spent_this_month_usd: f64,
    pub month_key: String, // "YYYY-MM" format
}

impl AgentBudget {
    pub fn current_month_key() -> String {
        // Use chrono in production; simplified here
        let secs = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let days = secs / 86400;
        format!("month-{}", days / 30)
    }

    pub fn reset_if_new_month(&mut self) {
        let current = Self::current_month_key();
        if self.month_key != current {
            self.spent_this_month_usd = 0.0;
            self.month_key = current;
        }
    }
}

pub struct BudgetTracker {
    budgets: Mutex<HashMap<String, AgentBudget>>,
}

impl BudgetTracker {
    pub fn new(configs: Vec<AgentBudget>) -> Self {
        let map = configs.into_iter().map(|b| (b.agent_id.clone(), b)).collect();
        Self { budgets: Mutex::new(map) }
    }

    /// Deduct cost and return updated status. Call before each inference dispatch.
    pub async fn deduct_and_check(&self, agent_id: &str, cost_usd: f64) -> BudgetStatus {
        let mut budgets = self.budgets.lock().await;
        let budget = match budgets.get_mut(agent_id) {
            Some(b) => b,
            None => return BudgetStatus::Normal, // No budget configured → allow
        };
        budget.reset_if_new_month();
        budget.spent_this_month_usd += cost_usd;
        let pct = budget.spent_this_month_usd / budget.monthly_limit_usd;
        match pct {
            p if p >= 1.0 => BudgetStatus::Paused {
                reason: format!(
                    "Monthly limit ${:.2} reached (spent: ${:.2})",
                    budget.monthly_limit_usd, budget.spent_this_month_usd
                ),
            },
            p if p >= 0.8 => BudgetStatus::Warning { usage_pct: p },
            _ => BudgetStatus::Normal,
        }
    }

    pub async fn get_status(&self, agent_id: &str) -> BudgetStatus {
        self.deduct_and_check(agent_id, 0.0).await
    }

    /// Board override: manually set a new monthly limit.
    pub async fn override_budget(&self, agent_id: &str, new_limit_usd: f64) {
        let mut budgets = self.budgets.lock().await;
        if let Some(b) = budgets.get_mut(agent_id) {
            b.monthly_limit_usd = new_limit_usd;
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

[budget.kelk]
monthly_limit_usd = 50.0
```

---

### Borrow #4 — Context Mode → extend `agent.rs`

**Priority: 6/10 | Timeline: Week 3**

**Problem:** Factory routes all tasks identically — no way to specify minimal vs full context for task complexity. Observer tasks (Nan) and operator tasks (IG-88) receive the same context payload.

**Paperclip's solution:** `executionWorkspaceSettings` JSONB per task controls context depth. Thin = minimal prompt only. Fat = full context with goal ancestry and skills.

**Factory adaptation:** `ContextMode` enum in `agent.rs`, wired into `UserMessage` serialization.

```rust
// Extend src/coordinator-rs/src/agent.rs

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub enum ContextMode {
    #[default]
    Fat,    // Full context: memory injection + identity files + tool results
    Thin,   // Minimal: system prompt only, no memory injection
}

impl UserMessage {
    pub fn to_json_with_mode(&self, mode: &ContextMode) -> serde_json::Value {
        match mode {
            ContextMode::Fat => serde_json::json!({
                "role": self.role,
                "content": self.content,
                "content_blocks": self.content_blocks,
                "room_id": self.room_id,
                "event_id": self.event_id,
            }),
            ContextMode::Thin => serde_json::json!({
                "role": self.role,
                "content": self.content,
            }),
        }
    }
}
```

---

## 6. LEARN — Adapt Philosophy, Not Code

**Goal hierarchy cascading.** Paperclip propagates goals Mission → Project → Agent → Task so agents always know the "why" behind work. Factory does not have a formal goal ancestry model. This should be adopted as a design pattern in Loop Spec authoring — TOML Loop Specs should include explicit `[goal]` blocks that cascade from system mission to individual task. No code change required; this is a documentation and tooling convention.

**Single-operator framing.** Paperclip's UX is built around one human owning a company of agents. Factory is currently diffuse in its operator model. Tightening the "one operator, many agents" mental model would improve tooling focus and reduce ambiguity in approval routing. ATR002 should be updated to make this explicit.

**Approval SLA framing.** Paperclip treats approval timeouts as SLAs (1 hour for strategy deployment, 5 minutes for trading). Factory should adopt this framing explicitly rather than a single default timeout. The typed approval gates (Borrow #2) are the code implementation of this philosophy.

---

## 7. SKIP

| Pattern | Reason |
|---------|--------|
| Org chart hierarchy (Company/CEO/Department) | Incompatible with Factory's flat coordinator model; adoption requires full architectural redesign with no operational benefit at current agent count |
| Board voting (quorum logic) | Factory's ATR002 + HMAC approvals handle governance more deterministically with cryptographic proof of decision |
| Company portability / export templates | Not relevant to Factory's single-deployment model on Whitebox |
| Multi-agent hiring workflows | Factory uses manual agent instantiation; automated hiring adds complexity without current need |
| PostgreSQL migration | Rust + file-based state is simpler and sufficient for Factory's single-operator model; database adds infrastructure burden |
| Plugin ecosystem rebuild | Not needed until agent count exceeds 10; static MCP whitelist is adequate for current scale |

---

## 8. Implementation Roadmap

### Week 1

- [ ] Create `src/coordinator-rs/src/task_lease.rs` — `TaskLeaseManager` with `try_claim`, `renew_lease`, `release_lease`, `cleanup_expired`, `active_count`
- [ ] Integrate `task_lease` into coordinator dispatch loop — wrap `dispatch_to_agent()` with `try_claim` / `release_lease`
- [ ] Add `cleanup_expired()` call to coordinator maintenance loop (every 60 seconds)
- [ ] Add `ApprovalGateType` enum to `approval.rs`
- [ ] Add `ApprovalGatePolicies` with `can_auto_approve()` and `approval_timeout_ms()`
- [ ] Add `#[serde(default)]` to `gate_type` on `ApprovalRecord` for backward compatibility

### Week 2

- [ ] Create `src/coordinator-rs/src/budget.rs` — `BudgetTracker` + `AgentBudget` + `BudgetStatus`
- [ ] Add `[budget.*]` config block to `coordinator.toml` (ig88, boot, kelk)
- [ ] Wire `deduct_and_check()` into agent message dispatch path before `send_to_agent()`
- [ ] Add `BudgetStatus::Paused` handling — block dispatch, post warning to Matrix STATUS_ROOM
- [ ] Add 80% threshold warning log with Matrix broadcast to monitoring room

### Week 3

- [ ] Add `ContextMode` enum to `agent.rs`
- [ ] Add `to_json_with_mode()` to `UserMessage`
- [ ] Wire `ContextMode::Thin` for Nan (observer role), `ContextMode::Fat` for all operator agents
- [ ] Add `ApprovalGateType` to `dispatch_to_agent()` call sites — classify each dispatch by gate type

### Success Metrics

- Zero double-claim incidents in IG-88 task queue under concurrent dispatch tests
- IG-88 monthly budget usage visible in coordinator logs at each inference call
- `LoopSpecDeploy` approval requests enforce 1-hour timeout with no auto-approve path
- `TradingExecution` approvals enforce 5-minute timeout distinct from `ToolCall` 1-minute timeout
- `BudgetStatus::Paused` blocks dispatch and posts a clear reason before any monthly limit breach
- Nan dispatches produce measurably smaller payloads than IG-88 dispatches

---

## 9. Risk Assessment

| Borrow | Failure Mode | Mitigation |
|--------|-------------|------------|
| `task_lease.rs` | Coordinator restart drops all in-memory leases | Leases expire via TTL (5 min); safe to drop — no persistent state lost |
| `task_lease.rs` | Agent crashes mid-task, lease never released | TTL-based expiry automatically handles orphaned leases |
| `task_lease.rs` | task_id not consistently generated per dispatch | Define deterministic task_id generation (hash of room_id + event_id) |
| `approval.rs` types | Existing approval response files have no `gate_type` field | `#[serde(default)]` on `gate_type` — old files deserialize as `ToolCall` |
| `approval.rs` types | Operator doesn't notice different timeout semantics in Element | Include gate type in approval Matrix message body (e.g., `[TradingExecution — 5 min]`) |
| `budget.rs` | MLX token costs are hard to measure exactly | Track by invocation count as proxy until per-token cost API available from MLX-LM |
| `budget.rs` | Month rollover races with mid-task deduction | `reset_if_new_month()` is called inside the lock; no race |
| `budget.rs` | Budget state lost on coordinator restart | On restart, budget starts at zero for current month — conservative, not dangerous |
| `ContextMode` | Wrong mode assigned to task | Default is `Fat` (conservative); `Thin` must be explicitly requested |

---

## 10. Appendix: Matrix Substrate Post-Adaptation

*This section addresses the question: how does Matrix/Element's role change when the 3 Paperclip borrows are implemented?*

### What Does Not Change

All task dispatch still flows through Matrix messages to agent rooms. The operator still lives in Element. Pantalaimon provides E2EE (Megolm) transparently. The Matrix DAG event ordering provides an immutable audit trail. Federation remains possible.

`task_lease.rs` is entirely internal to coordinator-rs — it gates dispatch *before* a Matrix message is sent. Matrix never sees rejected claims. This is correct behavior; Element does not need to know about lease contention.

### What Changes or Gets Exposed

**Typed Approval Gates — the critical gap.** The current emoji reaction model (✅/❌) is adequate for `ToolCall` approvals. It breaks down for `TradingExecution` and `LoopSpecDeploy`. Both look identical in Element — text message + emoji. The operator cannot distinguish "approve this read query" from "approve a trade" from visual inspection alone.

Typed gates require one of:
1. **Gate type in the Matrix message body** — minimum viable: include `[gate_type=TradingExecution — 5 min timeout]` in the coordinator's approval message so the operator sees the type.
2. **Custom Matrix event types** — `m.approval.gate.*` structured events that a future Element widget could render contextually.
3. **Custom Element bot/widget** — renders approval buttons with contextual UI per gate type.

The minimum viable path is option 1 (text annotation), which requires only a change to the approval message formatting in coordinator.rs.

**Budget Tracking — new Matrix broadcast points.** `budget.rs` introduces side-channel broadcasts that do not exist today:
- 80% threshold: coordinator posts warning to `STATUS_ROOM_ID`
- 100% threshold: coordinator posts pause announcement to the agent's own room *and* to `STATUS_ROOM_ID`
- Budget override: when operator manually resets a budget, coordinator confirms in `STATUS_ROOM_ID`

A dedicated `BUDGET_MONITOR_ROOM` constant should be added to coordinator.rs for budget-specific broadcasts, keeping them separate from task approval traffic in `COORD_APPROVAL_ROOM`.

**Budget override path via Matrix.** When an agent is paused for budget, the operator needs a way to override from Element. Options:
- A typed `BudgetOverride` approval gate (already defined in Borrow #2) that coordinator generates automatically on hard pause — operator reacts to unblock.
- A text command in the monitoring room (e.g., `/reset-budget ig88 600`) parsed by coordinator.

### Factory's Enduring Matrix Advantages

| Advantage | Why Paperclip Cannot Replicate |
|-----------|-------------------------------|
| E2EE (Megolm) | Paperclip is TLS-only; no end-to-end encryption between operator and agents |
| DAG event ordering | Matrix's cryptographic event chain provides tamper-evident audit trail |
| Federated routing | Agents could operate across homeservers; Paperclip is single-deployment |
| Human-readable audit | Operator can read full agent transcript in Element without a custom dashboard |
| Async room-based routing | Messages persist in rooms; agents can re-read context; REST is stateless |

### Verdict

Matrix survives the Paperclip adaptations intact, with one required change: typed approval gate messages must include the gate type visibly in the Matrix message body so the operator knows what they are approving. Everything else is additive (new broadcast points) rather than structural. The borrowed Paperclip patterns do not erode Matrix's core advantages.

---

## 11. Conclusions

Paperclip is a well-engineered orchestration platform solving the same problem space from a different angle. The two systems reflect different constraints: Paperclip optimizes for human readability, org hierarchy, and cost transparency; Factory optimizes for determinism, cryptographic integrity, and local inference.

Factory should not abandon its architectural advantages — local MLX inference, Matrix E2EE substrate, Graphiti temporal memory, HMAC-signed approvals — to adopt Paperclip wholesale. The migration cost would be total and the regression in security and inference capability would be severe.

However, Paperclip has solved four concrete coordination problems that Factory has not addressed: concurrent task claiming, typed approval semantics, per-agent cost enforcement, and context mode routing. These are bounded, tractable additions to coordinator-rs that map cleanly to existing module boundaries. They carry no architectural risk and directly address operational gaps that become more significant as IG-88's trading workloads scale.

The borrow list — `task_lease.rs`, typed `approval.rs`, `budget.rs`, `ContextMode` — is the right output of this study.

---

## References

[1] Paperclip platform documentation. https://paperclip.ing/docs. Accessed 2026-03-17.
[2] Paperclip source repository. https://github.com/paperclipai/paperclip. MIT license. Accessed 2026-03-17.
[3] Paperclip heartbeat service. `paperclipai/paperclip/server/src/services/heartbeat.ts`. 108.5KB. Accessed 2026-03-17.
[4] Paperclip budget service. `paperclipai/paperclip/server/src/services/budgets.ts`. 31.7KB. Accessed 2026-03-17.
[5] Paperclip approvals service. `paperclipai/paperclip/server/src/services/approvals.ts`. 9.1KB. Accessed 2026-03-17.
[6] Paperclip issues service. `paperclipai/paperclip/server/src/services/issues.ts`. 53.4KB. Accessed 2026-03-17.
