# FCT009 Autoscope Integration — Autoresearch Loop Engine for coordinator-rs

**Date:** 2026-03-17
**Status:** Research Complete
**Sprint:** Three-agent autoscope integration research

---

## 1. Executive Summary

Three-agent research sprint exploring the autoresearch ecosystem and its integration path into coordinator-rs. The sprint covered three axes: (1) the `~/dev/autoresearch/` local repo structure and design patterns, (2) the upstream `karpathy/autoresearch` reference architecture on GitHub, and (3) the coordinator-rs integration gaps that must be closed to support Loop Spec execution. The deliverable is a complete design for the loop engine that weaves autoscope's Loop Spec system into coordinator-rs as a first-class subsystem.

---

## 2. Upstream Reference — karpathy/autoresearch

### Architecture

The upstream project consists of three core files that establish a clean separation of concerns:

- **`prepare.py`** — Frozen evaluation harness. Downloads data, builds tokenizer, creates train/val splits. The agent cannot modify this file.
- **`train.py`** — Mutable surface. The only file the agent is permitted to change. Contains the model architecture, training loop, and hyperparameters.
- **`program.md`** — Agent instructions. Defines the research objective, constraints, and iteration protocol.

### Core Pattern: Modify-Commit-Run-Evaluate

Each iteration follows a deterministic cycle:

1. **Modify** `train.py` (the sole mutable surface)
2. **Commit** the change to git
3. **Run** training (5-minute wall-clock budget per iteration)
4. **Evaluate** against `val_bpb` (validation bits-per-byte)
5. **Keep or discard** — improvement triggers commit retention; regression triggers `git reset`

### Safety Model

- Fixed time budget per iteration (5 minutes wall-clock)
- Frozen evaluation harness — the agent cannot modify the metric computation
- Timeout enforcement prevents runaway iterations
- "NEVER STOP" autonomous operation, but only within bounded constraints
- Git provides full rollback capability at every iteration boundary

### Technology Stack

Python 3.10+, PyTorch 2.9.1, Flash Attention 3, rustbpe tokenizer, uv package manager.

### Key Insight

The frozen/mutable contract is the crown jewel of the design. Bounded autonomy within a fixed evaluation framework ensures the agent can explore freely without gaming the metric or breaking the evaluation pipeline. This is the pattern autoscope generalizes.

---

## 3. Factory's autoscope Layer (ATR002)

### What autoscope Adds

autoscope extends the upstream pattern into a general-purpose loop governance system:

- **Explicit Loop Spec YAML** — declarative specification for any autonomous loop
- **Five loop types** — researcher, narrative, infra-improve, coding, research-swarm
- **Composable budget model** — per-iteration and monthly limits, independently enforced
- **Multi-agent safety** — each agent type has scoped frozen/mutable boundaries
- **Gaming checks** — metric integrity rules reject gameable or self-reported metrics
- **Formal rollback semantics** — git-based rollback with defined trigger conditions

### Agent Constitution

The autoscope agent is defined in `.claude/agents/autoscope.md` with five scoping skills:

| Skill | Purpose |
|-------|---------|
| `scope-researcher-loop` | Research iteration loops |
| `scope-narrative-loop` | IG-88 narrative/trading loops |
| `scope-infra-loop` | Boot infrastructure improvement loops |
| `scope-coding-loop` | Ralph coding/test loops |
| `scope-swarm` | Multi-branch research swarms |

### Loop Spec Schema

```yaml
loop_type: researcher | narrative | infra-improve | coding | research-swarm
agent: <agent_id>
objective: <string>
metric:
  name: <string>
  formula: <string>
  baseline: <number>
  direction: minimize | maximize
  machine_readable: true | false
frozen_harness: []        # paths the agent MUST NOT modify
mutable_surface: []       # paths the agent MAY modify
budget:
  per_iteration: <duration | token_count>
  max_iterations: <int>
rollback_mechanism: git_reset | git_revert | manual
approval_gate: none | human | propose-then-execute
invocation: <string>
worker_cwd: <path>
loop_spec_path: <path>
```

### Integrity Rules

1. Reject gameable metrics (self-reported, no external validation)
2. Coordinator binary is always frozen
3. Soul/principles files are always frozen
4. No unbounded budgets — `max_iterations` is mandatory
5. Observed failure required before infra-improve loops are approved

### Current Status

Design complete. The `loop-specs/` directory exists but is empty — zero specs have been executed. This document defines the integration path to make execution possible.

---

## 4. Five Loop Types — Detailed Mapping

### 4.1 Researcher Loop

**Purpose:** Autonomous research iteration with source-validated signal density.

| Attribute | Value |
|-----------|-------|
| Metric | `research_signal_density` (floor: 3 unique sources) |
| Approval | None — fully autonomous |
| Frozen harness | Research question definition, evaluation pipeline, `notes/`, `specs/` |
| Rollback | Git reset on signal density regression |
| Budget | Per-iteration time + max iterations |

### 4.2 Narrative Loop (IG-88)

**Purpose:** Rolling market narrative accuracy for trading agent context.

| Attribute | Value |
|-----------|-------|
| Metric | `narrative_accuracy_rate` (7-day rolling window) |
| Approval | None — autonomous within Governor risk limits |
| Frozen harness | Governor risk limits, Jupiter/KuCoin MCP config, 15-minute autonomous cycle prompt |
| Rollback | Git reset on accuracy regression |
| Budget | Per-iteration: 15 minutes; iterations: rolling continuous |

### 4.3 Infra-Improve Loop (Boot)

**Purpose:** Reduce approval friction through infrastructure automation. Additive-only: the auto-approve list can expand but never shrink.

| Attribute | Value |
|-----------|-------|
| Metric | `approval_friction_rate` (additive-only constraint) |
| Approval | Human required before merge |
| Frozen harness | Coordinator binary, security validator, `pretool-approval.sh`, all `soul/principles/`, `max_claude_sessions` |
| Rollback | Git revert (preserves audit trail) |
| Budget | Per-iteration + monthly agent budget |
| Prerequisite | Observed failure required before loop is approved |

### 4.4 Coding Loop (Ralph Loop)

**Purpose:** Test-driven code improvement with human checkpoints.

| Attribute | Value |
|-----------|-------|
| Metric | `test_pass_delta` (fallback: `build_success + linter_clean`) |
| Approval | Propose-then-execute (human review every 5 iterations) |
| Frozen harness | Test files, dependency manifests, build/CI configuration |
| Rollback | Git reset on test regression |
| Protocol | Brief Matrix post per iteration; git commit on improvement; git reset on regression |
| Budget | Per-iteration time + max iterations with human checkpoint |

### 4.5 Research Swarm

**Purpose:** Multi-branch parallel research with synthesis deduplication.

| Attribute | Value |
|-----------|-------|
| Metric | `synthesis_coverage` (unique findings / sum of branch findings) |
| Approval | Human required before synthesis promoted from `inbox/` to `notes/` |
| Frozen harness | `swarm_id`, angle definitions frozen after spawn |
| Write target | Per-branch: `inbox/{swarm_id}-{angle}.md` |
| Rollback | Branch deletion on coverage regression |
| Budget | Per-branch iteration budget + swarm-level max branches |

---

## 5. coordinator-rs Integration Gap Analysis

### What Exists (from Paperclip x Factory Sprint — FCT008)

The FCT004-FCT008 sprint delivered several subsystems that the loop engine can build on:

| Component | File | Relevant Capability |
|-----------|------|---------------------|
| `ApprovalGateType` | `approval.rs` | 5 variants including `LoopSpecDeploy` |
| `BudgetTracker` | `budget.rs` | Monthly limits, soft/hard thresholds, incident logging |
| `RuntimeStateManager` | `runtime_state.rs` | Token/cost tracking per agent |
| `RunEventLog` | `run_events.rs` | Append-only JSONL event stream |
| `TaskLeaseManager` | `task_lease.rs` | Atomic task checkout with expiry |
| `ContextMode` | `context.rs` | Fat/Thin context switching |

### What's Missing

| # | Gap | Description | Blocked By |
|---|-----|-------------|------------|
| 1 | Loop Spec reader | No YAML parser for Loop Spec schema | New module |
| 2 | Loop state machine | No `ActiveLoop` lifecycle (init, running, paused, complete, failed) | New module |
| 3 | Frozen harness enforcement | No runtime check that agent writes stay within `mutable_surface` | Integration point |
| 4 | Per-iteration budget | Budget only tracks monthly; no per-iteration reset | `budget.rs` extension |
| 5 | `LoopIteration` gate type | No approval gate for iteration-level checkpoints | `approval.rs` extension |
| 6 | `InfraChange` gate type | No approval gate for infra-improve merge approval | `approval.rs` extension |
| 7 | Loop lifecycle events | No `RunEvent` variants for loop start/iteration/complete/fail/rollback/pause | `run_events.rs` extension |
| 8 | Loop constraint prompt injection | No mechanism to inject frozen/mutable paths into agent system prompt | `agent.rs` extension |
| 9 | Rollback trigger | No automated `git reset` / `git revert` on metric regression | New module |
| 10 | Loop config fields | No `LoopConfig` in coordinator config schema | `config.rs` extension |

---

## 6. Frozen Harness Enforcement Strategy

Three-layer defense ensures agents cannot modify frozen paths, with each layer catching different failure modes:

### Layer 1 — Prompt Injection (Preventive)

At dispatch time, inject the frozen/mutable path lists into the agent's system prompt. The agent receives explicit instructions about which paths it may and may not modify. This is a soft constraint — it relies on LLM instruction-following.

### Layer 2 — Runtime Interception (Active)

Intercept `InputRequest` tool calls (file writes, shell commands) before execution. Parse `tool_input` to extract target paths. Deny any write operation targeting a path in `frozen_harness[]`. Return an error message to the agent explaining the constraint violation.

### Layer 3 — Post-hoc Audit (Detective)

After each iteration completes, run `git diff --name-only` against the iteration's starting commit. Compare changed files against `frozen_harness[]`. If any frozen file was modified (e.g., through an indirect mechanism that bypassed Layer 2), trigger immediate rollback and log a security incident.

---

## 7. Budget Composition Model

Two independent budget dimensions are checked at every iteration boundary:

```
Per-iteration budget (from Loop Spec)
  + Monthly agent budget (from budget.rs)
  = Both checked independently; tighter constraint wins
```

- **Per-iteration budget** resets at each iteration boundary. Measured in wall-clock time or token count, depending on loop type.
- **Monthly budget** accumulates across all iterations and all loops for the agent. Tracked by the existing `BudgetTracker`.
- **Enforcement:** If either budget is exhausted, the loop pauses. Per-iteration exhaustion triggers iteration rollback. Monthly exhaustion triggers loop suspension with a `BudgetExhausted` event.

---

## 8. Implementation Roadmap

### Phase 1 — `loop_engine.rs` (New Module)

- `LoopSpec` struct with serde YAML deserialization
- `ActiveLoop` state machine: `Init -> Running -> Paused -> Complete | Failed`
- `LoopManager` orchestrator: load specs, track active loops, drive iteration lifecycle
- `LoopMetricResult` struct for iteration evaluation

### Phase 2 — `approval.rs` Extension

- Add `LoopIteration` variant to `ApprovalGateType` (iteration checkpoint approval)
- Add `InfraChange` variant to `ApprovalGateType` (infra-improve merge approval)
- Wire iteration checkpoint logic: every N iterations, pause and request human review

### Phase 3 — `run_events.rs` Extension

Six new event types:

- `LoopStarted { loop_id, spec_path, agent }`
- `LoopIterationComplete { loop_id, iteration, metric_value, kept }`
- `LoopPaused { loop_id, reason }`
- `LoopComplete { loop_id, iterations_total, final_metric }`
- `LoopFailed { loop_id, iteration, error }`
- `LoopRollback { loop_id, iteration, from_commit, to_commit }`

### Phase 4 — `config.rs` Extension

- `LoopConfig` struct: default budget limits, loop-specs directory path, enabled loop types, max concurrent loops
- Integration with existing `CoordinatorConfig`

### Phase 5 — `coordinator.rs` Integration (Depends on Phases 1-4)

- Frozen harness check at dispatch (Layer 2 runtime interception)
- `!loop` Matrix commands: `!loop start <spec>`, `!loop status`, `!loop pause <id>`, `!loop stop <id>`
- Iteration lifecycle: pre-iteration budget check, post-iteration metric evaluation, rollback-or-keep decision

### Phase 6 — `agent.rs` Extension

- Loop constraint prompt builder: injects frozen/mutable paths, iteration number, budget remaining, and metric target into agent system prompt at dispatch time

### Parallelization

Phases 1-4 are independent and can be developed in parallel. Phase 5 depends on all four. Phase 6 can proceed in parallel with Phase 5.

---

## 9. Loop Type Support Matrix

| Loop Type | Approval Gate | Frozen Harness Scope | Budget Type | Rollback Method |
|-----------|---------------|---------------------|-------------|-----------------|
| Researcher | None | Question + eval pipeline + notes/ + specs/ | Per-iteration time | `git reset` |
| Narrative | None | Governor limits + MCP config + cycle prompt | Per-iteration time (15 min) | `git reset` |
| Infra-Improve | `InfraChange` (human) | Coordinator + security + pretool + soul + max_sessions | Per-iteration + monthly | `git revert` |
| Coding | `LoopIteration` (every 5) | Tests + deps + build/CI | Per-iteration + monthly | `git reset` |
| Research Swarm | Human (synthesis promotion) | swarm_id + angle definitions | Per-branch iteration | Branch deletion |

---

## 10. References

[1] karpathy/autoresearch, GitHub, https://github.com/karpathy/autoresearch

[2] ATR001 — autoresearch System Analysis and Blackbox Integration Opportunities

[3] ATR002 — autoscope Agent Design

[4] FCT004 — Paperclip vs Factory Architecture Study and Adoption Assessment

[5] FCT007 — Paperclip Deep-Dive: 14 Additional Patterns for Factory

[6] FCT008 — Sprint Complete: Paperclip x Factory Gap Analysis and Implementation
