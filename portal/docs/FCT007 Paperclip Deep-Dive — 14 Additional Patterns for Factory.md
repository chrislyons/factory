# FCT007 Paperclip Deep-Dive — 14 Additional Patterns for Factory

**Prefix:** FCT
**Repo:** `~/dev/factory/`
**Date:** 2026-03-17
**Status:** Active
**Related:** FCT004, FCT001, FCT002, BKX074

---

## 1. Executive Summary

FCT004 studied the Paperclip orchestration platform [2] against Factory's coordinator-rs and identified 4 high-priority patterns to borrow: atomic task checkout, typed approval gates, per-agent budget tracking, and context mode routing. Those 4 patterns are being implemented in the current sprint (Borrows #1–#4).

This document reports the findings of a second-pass deep-dive conducted by a 3-agent parallel research team (researcher, implementer, doc-writer) against the same Paperclip codebase. The team surfaced 14 additional patterns — numbered #5 through #18 in a unified catalog — that were not covered in FCT004's initial assessment.

**Methodology:** Parallel agents independently read Paperclip's `heartbeat.ts` (108.5KB), `issues.ts` (53.4KB), `budgets.ts` (31.7KB), and `approvals.ts` (9.1KB) service files, cross-referencing the DATABASE.md schema [3], SPEC.md [4], and SPEC-implementation.md [5]. Patterns were identified by searching for constructs with no equivalent in coordinator-rs source (~6,677 lines across coordinator.rs, agent.rs, approval.rs, lifecycle.rs, timer.rs).

**Sprint outcome:** Patterns #5–#8 were implemented in this sprint. Patterns #9–#18 are catalogued for future consideration.

### Summary Table — All 18 Patterns

| # | Pattern | Priority | Complexity | Sprint Status |
|---|---------|----------|------------|---------------|
| 1 | Atomic Task Checkout | 9/10 | LOW | FCT004 (implementing) |
| 2 | Typed Approval Gates | 8.5/10 | LOW | FCT004 (implementing) |
| 3 | Per-Agent Budget Tracking | 7.5/10 | MEDIUM | FCT004 (implementing) |
| 4 | Context Mode (Thin/Fat) | 6/10 | LOW | FCT004 (implementing) |
| 5 | Budget Incidents (Soft/Hard) | 8/10 | LOW | **Implemented this sprint** |
| 6 | Session Compaction | 7.5/10 | MEDIUM | **Implemented this sprint** |
| 7 | Cumulative Runtime State | 7/10 | MEDIUM | **Implemented this sprint** |
| 8 | Heartbeat Event Streaming | 7/10 | MEDIUM | **Implemented this sprint** |
| 9 | Wakeup Request Coalescing | 5.5/10 | MEDIUM | Catalogued — future |
| 10 | Context Snapshots | 5/10 | LOW | Catalogued — future |
| 11 | Log Store Abstraction | 5/10 | MEDIUM | Catalogued — future |
| 12 | Execution Workspaces | 5/10 | MEDIUM | Catalogued — future |
| 13 | Issue Work Products | 4.5/10 | LOW | Catalogued — future |
| 14 | Approval Comments | 4.5/10 | LOW | Catalogued — future |
| 15 | Agent Config Revisions | 4/10 | LOW | Catalogued — future |
| 16 | Documents with Revisions | 3.5/10 | LOW | Catalogued — future |
| 17 | Issue Approvals (Task-Level Gates) | 3.5/10 | LOW | Catalogued — future |
| 18 | Finance Events | 2/10 | LOW | Catalogued — future |

---

## 2. Patterns Implemented This Sprint (#5–#8)

### Pattern #5 — Budget Incidents (Soft/Hard)

**Relevance: 8/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

Budget incidents extend basic budget tracking (Borrow #3 / `budget.rs`) with structured threshold violation records. Paperclip uses a two-tier model:

- **Soft incident (80%):** Coordinator emits a warning, notifies the operator, but execution continues.
- **Hard incident (100%):** Coordinator auto-pauses the agent, creates a formal incident record, and requires operator intervention (a `BudgetOverride` approval gate) to resume.

Incident records are stored with timestamp, threshold type, usage percentage at time of violation, and agent ID. This creates a searchable history of budget boundary events — useful for capacity planning and auditing runaway agent costs.

#### Paperclip Source

`server/src/services/budgets.ts` — `createBudgetIncident()`, `getBudgetIncidents()` functions. Budget incident records stored in `budgetIncidents` table: `id`, `agentId`, `companyId`, `type` (`soft|hard`), `usagePct`, `createdAt`. [4]

#### Relevance to Factory

Factory's `budget.rs` (implemented in Borrow #3) tracks per-agent spend and returns a `BudgetStatus` enum but creates no persistent record of threshold crossings. Without incident records, budget exhaustion is a runtime event with no history — an agent that burns its monthly limit leaves no audit trail. Budget incidents make threshold violations queryable and recoverable across coordinator restarts.

#### Complexity Estimate

1–2 days. Extends the existing `budget.rs` module. No new dependencies; incident log can be a JSONL file per agent in `~/.config/coordinator/budget-incidents/`.

#### Rust Mapping Sketch

```rust
// Extend src/coordinator-rs/src/budget.rs

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum IncidentThreshold {
    Soft,  // 80% — warn, continue
    Hard,  // 100% — pause, require override
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BudgetIncident {
    pub id: String,          // uuid v4
    pub agent_id: String,
    pub threshold: IncidentThreshold,
    pub usage_pct: f64,
    pub spent_usd: f64,
    pub limit_usd: f64,
    pub created_at: u64,     // Unix epoch seconds
}

pub struct IncidentStore {
    log_dir: PathBuf,
}

impl IncidentStore {
    pub fn new(log_dir: PathBuf) -> Self { Self { log_dir } }

    /// Append a budget incident to the agent's JSONL log.
    pub async fn record(&self, incident: &BudgetIncident) -> anyhow::Result<()> {
        let path = self.log_dir.join(format!("{}.jsonl", incident.agent_id));
        let mut file = tokio::fs::OpenOptions::new()
            .create(true).append(true).open(&path).await?;
        let line = serde_json::to_string(incident)? + "\n";
        tokio::io::AsyncWriteExt::write_all(&mut file, line.as_bytes()).await?;
        Ok(())
    }

    /// Return all incidents for an agent in creation order.
    pub async fn list(&self, agent_id: &str) -> anyhow::Result<Vec<BudgetIncident>> {
        let path = self.log_dir.join(format!("{}.jsonl", agent_id));
        if !path.exists() { return Ok(vec![]); }
        let raw = tokio::fs::read_to_string(&path).await?;
        raw.lines()
            .filter(|l| !l.is_empty())
            .map(|l| serde_json::from_str(l).map_err(Into::into))
            .collect()
    }
}

// In BudgetTracker::deduct_and_check() — emit incident on threshold crossing:
// if pct >= 1.0 && prev_pct < 1.0 { incident_store.record(Hard incident).await?; }
// if pct >= 0.8 && prev_pct < 0.8 { incident_store.record(Soft incident).await?; }
```

---

### Pattern #6 — Session Compaction

**Relevance: 7.5/10 | Complexity: MEDIUM | Estimated Implementation: 3–4 days**

#### Description

Long-running agent sessions accumulate context that degrades inference quality and inflates token costs. Paperclip triggers compaction when any of three thresholds are crossed:

- **Run count:** session exceeds 10 agent runs
- **Token count:** cumulative tokens exceed 100K
- **Session age:** session older than 24 hours

On compaction trigger, the coordinator generates a "handoff markdown" — a structured summary of what the agent has done, what decisions were made, and what state needs to carry forward — then starts a fresh session with only that summary as initial context.

This prevents the "infinite context spiral" where an agent's growing history degrades its own performance [6].

#### Paperclip Source

`server/src/services/heartbeat.ts` — `shouldCompactSession()`, `compactSession()`, `generateHandoffMarkdown()`. Thresholds configurable per agent via `agentConfig.compactionPolicy`. [3]

#### Relevance to Factory

Factory agents currently have no compaction mechanism. IG-88's trading loop and Boot's project loop can run indefinitely. On long-running tasks, context window saturation forces the agent to lose early context silently — there is no explicit handoff, no summary, no signal to the operator. Session compaction adds explicit lifecycle management and makes context window exhaustion a first-class event rather than a silent degradation.

This is especially relevant for Boot's multi-day project tasks where context carryover across heartbeats is load-bearing.

#### Complexity Estimate

3–4 days. Requires new `session_compaction.rs` module, threshold tracking integrated into cumulative runtime state (Pattern #7), and a compaction prompt template for generating handoff markdown via local MLX inference.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/session_compaction.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompactionPolicy {
    pub max_runs: u32,           // default: 10
    pub max_tokens: u64,         // default: 100_000
    pub max_age_secs: u64,       // default: 86_400 (24h)
}

impl Default for CompactionPolicy {
    fn default() -> Self {
        Self { max_runs: 10, max_tokens: 100_000, max_age_secs: 86_400 }
    }
}

#[derive(Debug, Clone)]
pub enum CompactionTrigger {
    RunCountExceeded { runs: u32 },
    TokenCountExceeded { tokens: u64 },
    AgeExceeded { age_secs: u64 },
}

pub struct SessionCompactor {
    policy: CompactionPolicy,
}

impl SessionCompactor {
    pub fn new(policy: CompactionPolicy) -> Self { Self { policy } }

    /// Check whether compaction should trigger given current runtime state.
    pub fn should_compact(
        &self,
        run_count: u32,
        total_tokens: u64,
        session_start: SystemTime,
    ) -> Option<CompactionTrigger> {
        let age_secs = SystemTime::now()
            .duration_since(session_start)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        if run_count >= self.policy.max_runs {
            return Some(CompactionTrigger::RunCountExceeded { runs: run_count });
        }
        if total_tokens >= self.policy.max_tokens {
            return Some(CompactionTrigger::TokenCountExceeded { tokens: total_tokens });
        }
        if age_secs >= self.policy.max_age_secs {
            return Some(CompactionTrigger::AgeExceeded { age_secs });
        }
        None
    }

    /// Generate a handoff markdown string from the agent's current session summary.
    /// Caller passes the summary prompt to local MLX inference and returns the result.
    pub fn compaction_prompt(
        &self,
        agent_id: &str,
        trigger: &CompactionTrigger,
        last_n_events: &[String],
    ) -> String {
        format!(
            "You are compacting the session for agent `{}`. \
             Trigger: {:?}. \
             Summarise the following events into a concise handoff context \
             that captures decisions made, current task state, and open items. \
             Events:\n{}",
            agent_id,
            trigger,
            last_n_events.join("\n")
        )
    }
}
```

---

### Pattern #7 — Cumulative Runtime State

**Relevance: 7/10 | Complexity: MEDIUM | Estimated Implementation: 2–3 days**

#### Description

Paperclip maintains a mutable per-agent runtime state record that accumulates across heartbeat runs within the same session. Fields tracked:

- **Session ID:** current active session identifier
- **Total tokens:** cumulative token consumption for this session
- **Cost cents:** cumulative inference cost in integer cents (avoids float drift)
- **Last run status:** `finished | error | paused | skipped`
- **Last error:** error message from most recent failed run, if any

This state is updated atomically on each session completion. It feeds into compaction decisions (Pattern #6), budget enforcement (Pattern #3/#5), and the operator dashboard. Without it, each agent run is isolated — no cross-run aggregation is possible.

#### Paperclip Source

`server/src/services/heartbeat.ts` — `AgentRuntimeState` interface, `updateRuntimeState()` function. Stored in `agentRuntimeState` table with unique index on `(companyId, agentId)`. [3]

#### Relevance to Factory

Factory currently has no per-agent runtime state aggregation. Budget tracking (Borrow #3) tracks cost per invocation but has no persistent per-session accumulator. Compaction (Pattern #6) requires token and run count totals. The operator has no visibility into cumulative session cost or run history without this.

#### Complexity Estimate

2–3 days. New `runtime_state.rs` module. State serialized to TOML/JSON in `~/.config/coordinator/runtime/`. Atomic file write on each update.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/runtime_state.rs

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    Finished,
    Error,
    Paused,
    Skipped,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentRuntimeState {
    pub agent_id: String,
    pub session_id: String,
    pub total_tokens: u64,
    pub cost_cents: u64,        // Integer cents — avoids float drift
    pub run_count: u32,
    pub session_start: u64,     // Unix epoch seconds
    pub last_run_status: RunStatus,
    pub last_error: Option<String>,
    pub updated_at: u64,
}

impl AgentRuntimeState {
    pub fn new(agent_id: &str) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH).unwrap().as_secs();
        Self {
            agent_id: agent_id.to_string(),
            session_id: uuid::Uuid::new_v4().to_string(),
            total_tokens: 0,
            cost_cents: 0,
            run_count: 0,
            session_start: now,
            last_run_status: RunStatus::Finished,
            last_error: None,
            updated_at: now,
        }
    }

    pub fn record_run(&mut self, tokens: u64, cost_cents: u64, status: RunStatus, error: Option<String>) {
        self.total_tokens += tokens;
        self.cost_cents += cost_cents;
        self.run_count += 1;
        self.last_run_status = status;
        self.last_error = error;
        self.updated_at = SystemTime::now()
            .duration_since(UNIX_EPOCH).unwrap().as_secs();
    }
}

pub struct RuntimeStateStore {
    state_dir: PathBuf,
}

impl RuntimeStateStore {
    pub fn new(state_dir: PathBuf) -> Self { Self { state_dir } }

    pub async fn load(&self, agent_id: &str) -> anyhow::Result<AgentRuntimeState> {
        let path = self.state_dir.join(format!("{}.json", agent_id));
        if path.exists() {
            let raw = tokio::fs::read_to_string(&path).await?;
            Ok(serde_json::from_str(&raw)?)
        } else {
            Ok(AgentRuntimeState::new(agent_id))
        }
    }

    /// Atomic write: write to .tmp then rename.
    pub async fn save(&self, state: &AgentRuntimeState) -> anyhow::Result<()> {
        let path = self.state_dir.join(format!("{}.json", state.agent_id));
        let tmp = path.with_extension("json.tmp");
        let raw = serde_json::to_string_pretty(state)?;
        tokio::fs::write(&tmp, raw).await?;
        tokio::fs::rename(&tmp, &path).await?;
        Ok(())
    }
}
```

---

### Pattern #8 — Heartbeat Event Streaming

**Relevance: 7/10 | Complexity: MEDIUM | Estimated Implementation: 2–3 days**

#### Description

Paperclip maintains an append-only event log per agent run. Each event has a monotonically incrementing sequence number and a typed payload. Event types:

| Event | Meaning |
|-------|---------|
| `session_start` | Agent run begins |
| `tool_call` | Agent requests a tool execution |
| `tool_result` | Tool execution result returned |
| `checkpoint` | Agent emits intermediate progress marker |
| `error` | Error occurred during run |
| `session_end` | Agent run completes |

Events are stored as JSONL files (one JSON object per line) — simple to write, stream-friendly, and easy to parse without loading the full log into memory. This provides a full per-run transcript that is distinct from the Matrix event log (which is encrypted and operator-facing) — the heartbeat event stream is coordinator-internal.

#### Paperclip Source

`server/src/services/heartbeat.ts` — `appendHeartbeatEvent()`, `HeartbeatEventType` enum, `heartbeatEvents` table. Sequence number maintained in `heartbeatRuns.lastEventSeq`. [3]

#### Relevance to Factory

Factory currently has no structured internal event log for agent runs. The Matrix message history is the only transcript. This is insufficient for: debugging failed runs (Matrix logs are E2EE and require Pantalaimon to read), feeding session compaction (Pattern #6) which needs the last N events, and auditing tool call sequences independent of the operator-facing channel.

Heartbeat event streaming is a foundation for several other patterns: compaction (needs event history), context snapshots (snapshot at event boundaries), and log store abstraction (events are what the log store persists).

#### Complexity Estimate

2–3 days. New `run_events.rs` module. JSONL append to per-run files in `~/.config/coordinator/runs/{run_id}.jsonl`.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/run_events.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "type")]
pub enum HeartbeatEvent {
    SessionStart { agent_id: String, session_id: String },
    ToolCall     { tool_name: String, input: serde_json::Value },
    ToolResult   { tool_name: String, output: serde_json::Value, success: bool },
    Checkpoint   { label: String, metadata: serde_json::Value },
    Error        { message: String, context: Option<String> },
    SessionEnd   { run_status: String, tokens_used: u64, cost_cents: u64 },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HeartbeatEventRecord {
    pub seq: u64,
    pub run_id: String,
    pub agent_id: String,
    pub timestamp: u64,        // Unix epoch millis
    pub event: HeartbeatEvent,
}

pub struct RunEventLog {
    log_dir: PathBuf,
    run_id: String,
    next_seq: std::sync::atomic::AtomicU64,
}

impl RunEventLog {
    pub fn new(log_dir: PathBuf, run_id: &str) -> Self {
        Self {
            log_dir,
            run_id: run_id.to_string(),
            next_seq: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub async fn append(&self, agent_id: &str, event: HeartbeatEvent) -> anyhow::Result<u64> {
        let seq = self.next_seq.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let record = HeartbeatEventRecord {
            seq,
            run_id: self.run_id.clone(),
            agent_id: agent_id.to_string(),
            timestamp: SystemTime::now()
                .duration_since(UNIX_EPOCH).unwrap().as_millis() as u64,
            event,
        };
        let path = self.log_dir.join(format!("{}.jsonl", self.run_id));
        let mut file = tokio::fs::OpenOptions::new()
            .create(true).append(true).open(&path).await?;
        let line = serde_json::to_string(&record)? + "\n";
        tokio::io::AsyncWriteExt::write_all(&mut file, line.as_bytes()).await?;
        Ok(seq)
    }

    /// Return the last N events for compaction use.
    pub async fn tail(&self, n: usize) -> anyhow::Result<Vec<HeartbeatEventRecord>> {
        let path = self.log_dir.join(format!("{}.jsonl", self.run_id));
        if !path.exists() { return Ok(vec![]); }
        let raw = tokio::fs::read_to_string(&path).await?;
        let records: Vec<HeartbeatEventRecord> = raw
            .lines()
            .filter(|l| !l.is_empty())
            .filter_map(|l| serde_json::from_str(l).ok())
            .collect();
        let start = records.len().saturating_sub(n);
        Ok(records[start..].to_vec())
    }
}
```

---

## 3. Patterns Catalogued for Future Implementation (#9–#18)

### Pattern #9 — Wakeup Request Coalescing

**Relevance: 5.5/10 | Complexity: MEDIUM | Estimated Implementation: 3–4 days**

#### Description

A separate queue for agent invocations that deduplicates concurrent wakeup signals before they reach the scheduling loop. Multiple sources (Matrix event, operator override, timer expiry, task assignment) can all trigger the same agent's wakeup within a short window. Without coalescing, the agent receives redundant invocations that waste tokens and produce duplicate outputs.

Coalescing uses idempotency keys — a hash of `(agent_id, trigger_source, window_key)` where `window_key` is a time-bucketed value (e.g., minute boundary). Multiple wakeup requests with the same key within the window collapse into a single invocation.

#### Paperclip Source

`server/src/services/heartbeat.ts` — `WakeupQueue`, `coalesceWakeupRequests()`, `idempotency_key` field on `heartbeatRuns`. [3]

#### Relevance to Factory

Factory's coordinator currently has no wakeup deduplication. If Boot receives a task via Matrix event and simultaneously a scheduled heartbeat fires, it will receive two invocations producing duplicate Matrix replies. This is rare at low agent counts but becomes a reliability issue as scheduled + event-driven invocations multiply. Medium priority — implement when invocation sources exceed 3.

#### Complexity Estimate

3–4 days. New `wakeup_queue.rs` module. Hash-based key dedup with configurable coalescing window (default: 60 seconds).

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/wakeup_queue.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InvocationSource {
    Scheduled,
    MatrixEvent,
    OperatorOverride,
    TimerExpiry,
    TaskAssigned,
}

#[derive(Debug, Clone)]
pub struct WakeupRequest {
    pub agent_id: String,
    pub source: InvocationSource,
    pub idempotency_key: String,
    pub requested_at: SystemTime,
    pub payload: Option<serde_json::Value>,
}

impl WakeupRequest {
    /// Compute the idempotency key: hash of agent_id + source type + minute bucket.
    pub fn compute_key(agent_id: &str, source: &InvocationSource) -> String {
        let bucket = SystemTime::now()
            .duration_since(UNIX_EPOCH).unwrap().as_secs() / 60;
        format!("{}-{:?}-{}", agent_id, source, bucket)
    }
}

pub struct WakeupQueue {
    pending: Mutex<HashMap<String, WakeupRequest>>,
    coalesce_window: Duration,
}

impl WakeupQueue {
    pub fn new(coalesce_window: Duration) -> Self {
        Self { pending: Mutex::new(HashMap::new()), coalesce_window }
    }

    /// Enqueue a wakeup request. Returns true if this is the first request for this key.
    pub async fn enqueue(&self, req: WakeupRequest) -> bool {
        let mut pending = self.pending.lock().await;
        let is_new = !pending.contains_key(&req.idempotency_key);
        pending.entry(req.idempotency_key.clone()).or_insert(req);
        is_new
    }

    /// Drain all pending requests that are ready to dispatch.
    pub async fn drain_ready(&self) -> Vec<WakeupRequest> {
        let mut pending = self.pending.lock().await;
        let now = SystemTime::now();
        let ready: Vec<String> = pending
            .iter()
            .filter(|(_, r)| now.duration_since(r.requested_at)
                .map(|d| d >= self.coalesce_window).unwrap_or(false))
            .map(|(k, _)| k.clone())
            .collect();
        ready.into_iter().filter_map(|k| pending.remove(&k)).collect()
    }
}
```

---

### Pattern #10 — Context Snapshots

**Relevance: 5/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

At each agent invocation, Paperclip serializes the full context payload used for that run — the goal ancestry, agent config, skills manifest, current task state, and memory injections — as a JSONB blob stored against the `heartbeatRun` record. This enables "decision replay": given a run ID, an operator can reconstruct exactly what context the agent had when it made a particular decision.

Context snapshots are distinct from the event log (Pattern #8) — the event log records what happened during the run; the snapshot records what the agent was given before the run started.

#### Paperclip Source

`server/src/services/heartbeat.ts` — `contextSnapshot` JSONB column on `heartbeatRuns` table. Populated by `captureContextSnapshot()` before `invokeAgent()`. [3]

#### Relevance to Factory

Factory currently has no per-invocation context record. When an agent produces an unexpected decision, the operator cannot determine whether it had the right context. This is particularly important for IG-88 trading decisions where post-hoc audit of "what did the agent know?" is required for compliance purposes.

Low complexity since the data already exists in coordinator state — this is a serialization + storage step, not new logic.

#### Complexity Estimate

1–2 days. Serialize `AgentInvocationContext` struct to JSON before dispatch; write to `~/.config/coordinator/snapshots/{run_id}.json`.

#### Rust Mapping Sketch

```rust
// In src/coordinator-rs/src/coordinator.rs — capture before dispatch

#[derive(Debug, Serialize, Deserialize)]
pub struct AgentInvocationContext {
    pub run_id: String,
    pub agent_id: String,
    pub invocation_source: String,
    pub task_summary: Option<String>,
    pub memory_injections: Vec<String>,
    pub skills_manifest: Vec<String>,
    pub config_snapshot: serde_json::Value,
    pub captured_at: u64,
}

// Before invoking agent:
// let snapshot = AgentInvocationContext { ... };
// tokio::fs::write(snapshots_dir.join(format!("{}.json", run_id)),
//     serde_json::to_vec_pretty(&snapshot)?).await?;
```

---

### Pattern #11 — Log Store Abstraction

**Relevance: 5/10 | Complexity: MEDIUM | Estimated Implementation: 3–5 days**

#### Description

Paperclip abstracts its transcript/log storage behind a `LogStore` trait that supports content-addressed (SHA-256) storage, optional compression, and deduplication. This allows the log backend to be swapped (local disk, S3, R2) without changing the heartbeat service. External log references are stored as `logRef` on `heartbeatRuns` — a URI pointing to the full transcript, not the transcript itself.

Content addressing ensures that identical transcripts (repeated no-op runs) are stored once. Deduplication at the storage layer prevents log explosion on agents that wake frequently with nothing to do.

#### Paperclip Source

`server/src/services/heartbeat.ts` — `LogStore` interface, `LocalLogStore`, `S3LogStore` implementations. `logRef` column on `heartbeatRuns`. Content-addressed via SHA-256 of the serialized JSONL content. [3]

#### Relevance to Factory

Factory's agent runs currently emit logs directly to stderr + Matrix room messages — no structured external storage. As run frequency increases (IG-88 trading cycles, Boot project loops), unmanaged log growth becomes a disk pressure issue on Blackbox. A log store abstraction with content addressing is the correct foundation for long-term observability. Not urgent now; relevant when weekly run volume exceeds ~1,000.

#### Complexity Estimate

3–5 days. Define `LogStore` trait in Rust; implement `LocalLogStore` (filesystem, SHA-256 keyed). Skip S3/R2 for now — add when Blackbox disk pressure materializes.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/log_store.rs

#[async_trait::async_trait]
pub trait LogStore: Send + Sync {
    /// Store log content; return content-addressed reference URI.
    async fn put(&self, content: &[u8]) -> anyhow::Result<String>;
    /// Retrieve log content by reference URI.
    async fn get(&self, log_ref: &str) -> anyhow::Result<Vec<u8>>;
    /// Check whether a reference exists.
    async fn exists(&self, log_ref: &str) -> anyhow::Result<bool>;
}

pub struct LocalLogStore {
    base_dir: PathBuf,
}

impl LocalLogStore {
    pub fn new(base_dir: PathBuf) -> Self { Self { base_dir } }

    fn content_ref(content: &[u8]) -> String {
        use sha2::{Sha256, Digest};
        format!("local://{}", hex::encode(Sha256::digest(content)))
    }
}

#[async_trait::async_trait]
impl LogStore for LocalLogStore {
    async fn put(&self, content: &[u8]) -> anyhow::Result<String> {
        let log_ref = Self::content_ref(content);
        let hash = log_ref.trim_start_matches("local://");
        let path = self.base_dir.join(&hash[..2]).join(hash);
        if !path.exists() {
            tokio::fs::create_dir_all(path.parent().unwrap()).await?;
            tokio::fs::write(&path, content).await?;
        }
        Ok(log_ref)
    }

    async fn get(&self, log_ref: &str) -> anyhow::Result<Vec<u8>> {
        let hash = log_ref.trim_start_matches("local://");
        let path = self.base_dir.join(&hash[..2]).join(hash);
        Ok(tokio::fs::read(&path).await?)
    }

    async fn exists(&self, log_ref: &str) -> anyhow::Result<bool> {
        let hash = log_ref.trim_start_matches("local://");
        Ok(self.base_dir.join(&hash[..2]).join(hash).exists())
    }
}
```

---

### Pattern #12 — Execution Workspaces

**Relevance: 5/10 | Complexity: MEDIUM | Estimated Implementation: 2–3 days**

#### Description

Paperclip creates a per-project isolated working directory for each agent's execution. The workspace lifecycle has four states:

| State | Meaning |
|-------|---------|
| `opened` | Directory created, not yet in use |
| `active` | Agent currently executing within it |
| `closed` | Execution complete, workspace retained |
| `cleanup_eligible` | Marked for deletion after retention period |

Workspace isolation prevents cross-project file collisions when multiple agents run concurrently on different projects. Cleanup eligibility is set after a retention period (default: 7 days) to allow post-hoc inspection before disk reclaim.

#### Paperclip Source

`server/src/services/issues.ts` — `ExecutionWorkspace` type, `createWorkspace()`, `activateWorkspace()`, `closeWorkspace()`. `executionWorkspaces` table with `lifecycleState` column. [6]

#### Relevance to Factory

Boot agent runs project work in its home directory without isolation. If Boot is simultaneously working two separate project tasks, file artifacts from one can bleed into the other's context. Per-project workspaces enforce clean separation. Moderate priority — implement when Boot begins concurrent project execution.

#### Complexity Estimate

2–3 days. New `workspace.rs` module. Workspaces as directories under `~/.config/coordinator/workspaces/{project_id}/`. Lifecycle state in a `state.json` file within each workspace directory.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/workspace.rs

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum WorkspaceLifecycle {
    Opened,
    Active,
    Closed { closed_at: u64 },
    CleanupEligible { eligible_at: u64 },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionWorkspace {
    pub id: String,
    pub project_id: String,
    pub agent_id: String,
    pub path: PathBuf,
    pub lifecycle: WorkspaceLifecycle,
    pub created_at: u64,
}

pub struct WorkspaceManager {
    base_dir: PathBuf,
    retention_secs: u64,   // default: 604_800 (7 days)
}

impl WorkspaceManager {
    pub fn new(base_dir: PathBuf, retention_secs: u64) -> Self {
        Self { base_dir, retention_secs }
    }

    pub async fn create(&self, project_id: &str, agent_id: &str) -> anyhow::Result<ExecutionWorkspace> {
        let id = uuid::Uuid::new_v4().to_string();
        let path = self.base_dir.join(project_id).join(&id);
        tokio::fs::create_dir_all(&path).await?;
        let ws = ExecutionWorkspace {
            id,
            project_id: project_id.to_string(),
            agent_id: agent_id.to_string(),
            path,
            lifecycle: WorkspaceLifecycle::Opened,
            created_at: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs(),
        };
        self.save_state(&ws).await?;
        Ok(ws)
    }

    async fn save_state(&self, ws: &ExecutionWorkspace) -> anyhow::Result<()> {
        let state_path = ws.path.join("state.json");
        tokio::fs::write(&state_path, serde_json::to_vec_pretty(ws)?).await?;
        Ok(())
    }
}
```

---

### Pattern #13 — Issue Work Products

**Relevance: 4.5/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

Paperclip tracks agent deliverables — files, PRs, branches, reports, deployed artifacts — as first-class objects linked to the task (issue) that produced them. Each work product has:

- **Stable key:** unique identifier within the issue
- **Type:** `file | pull_request | branch | report | artifact`
- **Title:** human-readable label
- **URL:** optional external reference (PR URL, branch URL)
- **Metadata:** JSONB for type-specific fields

Work products enable the operator to understand what an agent actually produced, not just that it "completed" a task. They survive session compaction — the handoff markdown can reference them by stable key.

#### Paperclip Source

`server/src/services/issues.ts` — `IssueWorkProduct` type, `createWorkProduct()`, `listWorkProducts()`. `issueWorkProducts` table. [6]

#### Relevance to Factory

Currently, Boot's project deliverables are visible only in the Matrix room transcript. There is no structured record of "Boot worked on issue #47 and produced PR #123, branch `feature/x`, and file `docs/FCT007.md`." Work products provide this structure. Low-medium priority — useful when Boot's output volume grows beyond what a human can track in Element.

#### Complexity Estimate

1–2 days. Simple struct + JSONL store per issue. No cross-cutting integration required initially.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/work_products.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkProductType {
    File,
    PullRequest,
    Branch,
    Report,
    Artifact,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueWorkProduct {
    pub key: String,           // stable, unique within issue
    pub issue_id: String,
    pub agent_id: String,
    pub product_type: WorkProductType,
    pub title: String,
    pub url: Option<String>,
    pub metadata: serde_json::Value,
    pub created_at: u64,
}
```

---

### Pattern #14 — Approval Comments

**Relevance: 4.5/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

Paperclip supports threaded discussion attached to approval requests. An agent can add a justification comment when submitting a request for approval. The operator can post clarifying questions. The agent (or coordinator) can respond. Each comment has: author (agent or operator), markdown body, timestamp. This replaces the current binary "approve or reject with no context" model.

The current Factory approval model is a HMAC-signed record + emoji reaction. There is no channel for the operator to ask "why does this need approval?" or for the agent to explain its reasoning without polluting the main task room.

#### Paperclip Source

`server/src/services/approvals.ts` — `ApprovalComment` type, `addApprovalComment()`. `approvalComments` table. [5]

#### Relevance to Factory

For `TradingExecution` and `LoopSpecDeploy` gate types, an operator receiving an approval request in Element benefits enormously from the agent's inline justification ("I am requesting to place a sell order on AAPL because momentum indicator crossed -2σ"). Without this, every approval is a cold context switch for the operator. The Matrix message body is a natural place to embed this; the data model just needs to persist it.

#### Complexity Estimate

1–2 days. Extend `ApprovalRecord` in `approval.rs` with a `justification: Option<String>` field and an `ApprovalComment` JSONL log per approval ID.

#### Rust Mapping Sketch

```rust
// Extend src/coordinator-rs/src/approval.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApprovalComment {
    pub approval_id: String,
    pub author: ApprovalCommentAuthor,
    pub body: String,          // Markdown
    pub created_at: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalCommentAuthor {
    Agent { agent_id: String },
    Operator { user_id: String },
}

// Extend ApprovalRequest:
// pub justification: Option<String>,  // Agent's reason for request
// pub comments: Vec<ApprovalComment>, // Threaded discussion
```

---

### Pattern #15 — Agent Config Revisions

**Relevance: 4/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

Paperclip stores an immutable, append-only revision history for every agent configuration change. Each revision has a sequential number, timestamp, author, and a diff of changed fields (with secret values redacted before persistence). The current config is always the highest-revision record.

This enables: rollback to a previous config, audit of who changed what and when, and safe debugging of "why did the agent start behaving differently last Tuesday?"

#### Paperclip Source

`server/src/services/issues.ts` (agent config path) — `AgentConfigRevision` type, revision numbering, `redactSecrets()` function applied before INSERT. [6]

#### Relevance to Factory

Factory's `AgentConfig` in `coordinator.toml` has no change history. A single TOML file overwrite produces no audit trail. Config revisions are a low-cost addition (append JSON to a log file on every config write) that makes operational debugging significantly easier. Low priority — implement when agent configs are changed more than weekly.

#### Complexity Estimate

1–2 days. On every `AgentConfig` write, serialize the new config (secrets redacted) to an append-only `{agent_id}-config-revisions.jsonl` file.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/config_revisions.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentConfigRevision {
    pub revision: u32,
    pub agent_id: String,
    pub config_snapshot: serde_json::Value,   // Secrets already redacted
    pub changed_by: String,
    pub created_at: u64,
}

pub fn redact_secrets(config: &serde_json::Value) -> serde_json::Value {
    // Recursively replace values whose keys match SECRET_KEYS with "[REDACTED]"
    const SECRET_KEYS: &[&str] = &["api_key", "token", "secret", "password", "credential"];
    // ... recursive JSON walk
    config.clone() // placeholder
}
```

---

### Pattern #16 — Documents with Revisions

**Relevance: 3.5/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

Paperclip treats documents (specifications, plans, reports produced by agents) as append-only versioned objects. Each document version is a new INSERT, never an UPDATE. The document has a `currentRevision` pointer and a full revision history. This ensures:

1. No decision document is ever silently overwritten
2. The operator can diff between versions
3. Agents can reference a specific revision by ID in later work

#### Paperclip Source

`server/src/services/issues.ts` — `Document` type, `DocumentRevision` type, `createDocumentRevision()`. Never uses UPDATE on document content. [6]

#### Relevance to Factory

Factory's docs live in the filesystem (Git-tracked). The Git history provides revision tracking for manually committed files. For agent-generated documents that do not go through Git (e.g., runtime reports, analysis outputs written by Boot), append-only versioning provides the same guarantee. Low priority — the Git convention covers most cases.

#### Complexity Estimate

1–2 days. Trivially implemented as a JSONL store of `{rev, content_ref, created_at}` per document ID.

#### Rust Mapping Sketch

```rust
// src/coordinator-rs/src/documents.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentRevision {
    pub doc_id: String,
    pub revision: u32,
    pub content_ref: String,       // log_store reference (Pattern #11)
    pub title: String,
    pub created_by: String,        // agent_id
    pub created_at: u64,
}
// Invariant: content is immutable once written. New version = new DocumentRevision.
```

---

### Pattern #17 — Issue Approvals (Task-Level Gates)

**Relevance: 3.5/10 | Complexity: LOW | Estimated Implementation: 2–3 days**

#### Description

Separate from the coordinator-level approval gate system (Borrow #2), Paperclip supports optional approval gates on specific tasks before they transition from `pending` to `in_progress`. This is a task-lifecycle gate, not an action gate. Gate types:

| Type | Use Case |
|------|----------|
| `safety_review` | High-risk task requires human review before agent starts |
| `budget_gate` | Task cost estimate exceeds threshold; operator must sign off |
| `stakeholder_sign_off` | External stakeholder approval required before execution |

Issue approvals are optional and configured per task, not globally. An issue without an approval gate transitions normally. An issue with an approval gate blocks at `pending` until the gate is cleared.

#### Paperclip Source

`server/src/services/approvals.ts` — `IssueApproval` type, `requiresApproval()`, gate status flow: `pending_approval → approved → in_progress` or `pending_approval → rejected`. [5]

#### Relevance to Factory

Factory's approval gates (Borrow #2) fire at action dispatch time — they block a specific action within a run. Issue approvals fire at task assignment time — they block the task from being picked up at all. For IG-88's high-stakes analysis tasks or Boot's irreversible operations, this provides an earlier, cheaper gate. Low priority — implement after typed approval gates are stable.

#### Complexity Estimate

2–3 days. Extend `task_lease.rs` with an optional `required_approval_gate` field on task records.

#### Rust Mapping Sketch

```rust
// Extend src/coordinator-rs/src/task_lease.rs or new task_approval.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IssueApprovalGateType {
    SafetyReview,
    BudgetGate,
    StakeholderSignOff,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueApproval {
    pub issue_id: String,
    pub gate_type: IssueApprovalGateType,
    pub status: IssueApprovalStatus,
    pub requested_at: u64,
    pub resolved_at: Option<u64>,
    pub resolved_by: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IssueApprovalStatus {
    PendingApproval,
    Approved,
    Rejected,
}
```

---

### Pattern #18 — Finance Events

**Relevance: 2/10 | Complexity: LOW | Estimated Implementation: 1–2 days**

#### Description

Paperclip includes an extensible event model for financial transactions associated with agent operations: subscription charges, API costs, infrastructure costs, refunds. Each event has a signed amount in cents (positive = revenue/income, negative = expense/refund), a category, and an extensible metadata payload.

This is primarily relevant for Paperclip's multi-tenant "zero-human company" model where companies can have real financial activity. Finance events provide a structured ledger distinct from the per-agent budget tracker (Pattern #3/#5).

#### Paperclip Source

`server/src/services/budgets.ts` — `FinanceEvent` type, `createFinanceEvent()`. `financeEvents` table: `id`, `companyId`, `type` (`revenue|expense|refund`), `category` (`subscription|api_cost|infrastructure`), `amount_cents`, `metadata`, `createdAt`. [4]

#### Relevance to Factory

Factory is a single-operator system on Blackbox. There are no revenue events, no subscription charges, and no external billing. The only finance events would be API cost expenses — already covered by budget incidents (Pattern #5). Finance events are overengineered for Factory's current scale. Catalogue for reference; do not implement unless Factory evolves into a multi-operator or commercial deployment.

#### Complexity Estimate

1–2 days if implemented. Not recommended at this time.

#### Rust Mapping Sketch (Reference Only)

```rust
// src/coordinator-rs/src/finance.rs (do not implement now)

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FinanceEventType { Revenue, Expense, Refund }

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FinanceCategory { Subscription, ApiCost, Infrastructure }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FinanceEvent {
    pub id: String,
    pub event_type: FinanceEventType,
    pub category: FinanceCategory,
    pub amount_cents: i64,         // Signed: positive = income, negative = expense
    pub metadata: serde_json::Value,
    pub created_at: u64,
}
```

---

## 4. Cross-Cutting Patterns

Several design principles recur across multiple Paperclip patterns. These are worth internalising as coordinator-rs conventions regardless of which individual patterns are adopted.

### 4.1 JSONB Extensibility

Paperclip attaches a `metadata: jsonb` column to nearly every entity. This allows schema evolution without migrations — new fields can be added to the metadata payload without altering the table. In coordinator-rs's file-based model, the equivalent is a `metadata: serde_json::Value` field on serialized structs with `#[serde(default)]` to remain backward-compatible on load.

**Convention for coordinator-rs:** Every new serialized struct should include `pub metadata: serde_json::Value` with `#[serde(default)]` to allow forward extension without breaking existing files.

### 4.2 Append-Only Histories

Paperclip never deletes or updates config revisions, document versions, budget incidents, or event logs. Everything is append-only. This matches Factory's existing HMAC approval record design and should be the universal default for any persistent state in coordinator-rs.

**Convention for coordinator-rs:** Any persistent record that might need revision (agent config, approval records, budget state) should be stored as an append-only log (JSONL), not an overwritten file. Current state = last record in the log.

### 4.3 Redaction on Persist

When Paperclip persists agent configs as revisions, it strips secret values before writing. The in-memory struct may contain a live API key; the revision log contains `"[REDACTED]"`. This prevents secret leakage into audit logs.

**Convention for coordinator-rs:** Any struct that may contain secrets (API keys, auth tokens) must be passed through a `redact_secrets()` transform before serialization to disk. A `Redactable` trait should be defined and implemented for all such structs.

```rust
// src/coordinator-rs/src/redact.rs
pub trait Redactable {
    /// Return a copy of self with sensitive fields replaced by "[REDACTED]".
    fn redacted(&self) -> Self;
}
```

### 4.4 Content-Addressed Storage

Paperclip's log store uses SHA-256 hashing to generate file addresses. Identical content produces the same address — automatic deduplication without explicit dedup logic. No-op agent runs that produce the same transcript are stored once.

**Convention for coordinator-rs:** Any high-volume data written to disk (run transcripts, snapshots) should use SHA-256 content addressing. Use a two-character directory prefix (first two hex chars of hash) to avoid filesystem inode exhaustion at high file counts.

---

## 5. Implementation Roadmap and Priority Ranking

### Tier 1 — Implement This Sprint (Already Done)

| # | Pattern | Module | Status |
|---|---------|--------|--------|
| 5 | Budget Incidents | `budget.rs` extension | Implemented |
| 6 | Session Compaction | `session_compaction.rs` | Implemented |
| 7 | Cumulative Runtime State | `runtime_state.rs` | Implemented |
| 8 | Heartbeat Event Streaming | `run_events.rs` | Implemented |

### Tier 2 — Next Sprint (High Operational Value)

| # | Pattern | Trigger |
|---|---------|---------|
| 9 | Wakeup Request Coalescing | When invocation sources > 3 or duplicates observed in logs |
| 14 | Approval Comments | When operator feedback required on approval requests |
| 10 | Context Snapshots | When IG-88 trading decisions require post-hoc audit |

### Tier 3 — Medium Term (Infrastructure)

| # | Pattern | Trigger |
|---|---------|---------|
| 11 | Log Store Abstraction | When Blackbox disk usage for runs exceeds 10GB |
| 12 | Execution Workspaces | When Boot begins concurrent project execution |
| 13 | Issue Work Products | When Boot output volume exceeds human tracking capacity |
| 15 | Agent Config Revisions | When agent configs change more than weekly |

### Tier 4 — Low Priority / Conditional

| # | Pattern | Trigger |
|---|---------|---------|
| 16 | Documents with Revisions | Only if agent-generated docs bypass Git |
| 17 | Issue Approvals | After typed approval gates (Borrow #2) stable for 30+ days |
| 18 | Finance Events | Only if Factory becomes multi-operator or commercial |

---

## 6. Dependency Graph

Some patterns depend on others being in place first:

```
runtime_state.rs (#7)
    └── session_compaction.rs (#6) — needs token + run count totals
        └── run_events.rs (#8) — needs event history for handoff generation

budget.rs (#3, FCT004)
    └── budget_incidents (#5) — extends existing BudgetTracker

log_store.rs (#11)
    └── documents.rs (#16) — uses log_store for content refs
    └── run_events.rs (#8) — can optionally back events to log_store

task_lease.rs (#1, FCT004)
    └── issue_approvals.rs (#17) — extends task lifecycle state
```

Patterns #10 (Context Snapshots), #12 (Workspaces), #13 (Work Products), #14 (Approval Comments), #15 (Config Revisions), and #18 (Finance Events) are standalone — no prerequisites.

---

## 7. Conclusions

The second-pass deep-dive surfaced 14 patterns across Paperclip's four core service files. Of these:

- **4 patterns (#5–#8) were implemented in this sprint** — budget incidents, session compaction, cumulative runtime state, and heartbeat event streaming — forming a coherent observability and lifecycle management layer.
- **6 patterns (#9–#14) are medium-priority** catalogue entries that become relevant as Factory's agent run volume scales.
- **4 patterns (#15–#18) are low-priority** with conditional adoption triggers, either dependent on config volatility (#15), agent output volume (#16), approval gate maturity (#17), or commercial evolution (#18).

The cross-cutting patterns — JSONB extensibility, append-only histories, redaction-on-persist, and content-addressed storage — should be adopted as coordinator-rs conventions immediately, independent of individual pattern adoption. They are zero-cost design choices that prevent architectural debt.

Together with FCT004's original 4 borrows, the full 18-pattern catalog represents a comprehensive extraction of Paperclip's design intelligence into Factory's Rust/Matrix architecture — without wholesale adoption or regression of Factory's core strengths.

---

## References

[1] Paperclip platform documentation. https://paperclip.ing/docs. Accessed 2026-03-17.
[2] Paperclip source repository. https://github.com/paperclipai/paperclip. MIT license. Version 0.3.1. Accessed 2026-03-17.
[3] Paperclip database schema. `paperclipai/paperclip/packages/db/`. Drizzle ORM schema definitions. Accessed 2026-03-17.
[4] Paperclip budget service. `paperclipai/paperclip/server/src/services/budgets.ts`. 31.7KB. Accessed 2026-03-17.
[5] Paperclip approvals service. `paperclipai/paperclip/server/src/services/approvals.ts`. 9.1KB. Accessed 2026-03-17.
[6] Paperclip issues service. `paperclipai/paperclip/server/src/services/issues.ts`. 53.4KB. Accessed 2026-03-17.
[7] Paperclip heartbeat service. `paperclipai/paperclip/server/src/services/heartbeat.ts`. 108.5KB. Accessed 2026-03-17.
[8] R. C. Martin, "Clean Architecture: A Craftsman's Guide to Software Structure and Design," Prentice Hall, 2017. Append-only event log pattern.
[9] A. Kleppmann, "Designing Data-Intensive Applications," O'Reilly Media, 2017. Content-addressed storage and immutable log design.
