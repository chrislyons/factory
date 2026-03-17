# FCT010 Autoscope Loop Engine — Sprint Completion Summary

**Status:** Complete
**Sprint:** 2026-03-17
**Scope:** coordinator-rs autoscope integration (FCT009 implementation)
**Repo:** `~/dev/factory/coordinator/`
**Previous:** FCT008 (Paperclip x Factory sprint), FCT009 (autoscope design doc)

---

## Objective

Implement the autoscope loop engine integration designed in FCT009 — enabling coordinator-rs to load, validate, enforce, and manage Loop Spec YAML files with frozen harness protection, per-iteration budgets, and structured lifecycle events.

---

## What Was Implemented

### Phase 1 — `loop_engine.rs` (new module, ~310 lines)

New file: `coordinator/src/loop_engine.rs`

- **`LoopSpec`** — YAML-deserializable struct matching autoscope schema: loop_id, name, objective, loop_type, agent_id, metric, frozen_harness, mutable_surface, budget, rollback, approval_gate, worker_cwd
- **`LoopType`** enum: Researcher, Narrative, InfraImprove, Coding, Swarm
- **`LoopMetric`** with `MetricDirection` (HigherIsBetter / LowerIsBetter) and `machine_readable` validation flag
- **`LoopBudget`** — per_iteration (token string), max_iterations
- **`RollbackMechanism`** — method (GitReset/ConfigRevert/FileDelete/TimerCancel), command, scope
- **`LoopApprovalGate`** enum: None, ProposeThenExecute, HumanApprovalRequired
- **`LoopSpec::load(path)`** — validates machine_readable: true and non-empty frozen_harness
- **`ActiveLoop`** — runtime state: status, current_iteration, iteration_tokens_used, total_tokens_used, best_metric, IterationRecord history
- **`ActiveLoop` methods**: is_budget_exceeded(), is_max_iterations_reached(), is_metric_improved(), record_iteration()
- **`LoopManager`** — HashMap-backed manager: load_and_register(), start_loop(), advance_iteration(), abort_loop(), complete_loop(), is_frozen(), deduct_iteration_tokens(), get_active_loops_for_agent()
- **Bug fix**: frozen path prefix matching normalises trailing slashes to prevent `"tests//"` double-slash false negatives

### Phase 2 — `approval.rs`

Added two new `ApprovalGateType` variants:
- **`LoopIteration`** — 300s timeout, blocking, not auto-approvable. For coding loop propose-then-execute gates.
- **`InfraChange`** — 3600s timeout, blocking, not auto-approvable. For infra-improve human-required gates.

All match arms (timeout_ms, can_auto_approve, is_blocking, label, Display) updated. Tests extended.

### Phase 3 — `run_events.rs`

Added 6 new `RunEventType` variants:
- `LoopStart`, `IterationStart`, `IterationEnd`, `LoopComplete`, `LoopAborted`, `FrozenHarnessViolation`

### Phase 4 — `config.rs`

Added three optional fields to `Settings`:
- `loop_specs_dir: Option<String>` — path to Loop Spec YAML directory
- `loop_state_file: Option<String>` — persistence file for active loop state
- `loop_max_concurrent: Option<u32>` — max simultaneous loops (default: 2)

Tilde/HOME expansion wired into `expand_paths()`.

### Phase 5 — `coordinator.rs`

Integrated `LoopManager` into `CoordinatorState`:
- `loop_manager: LoopManager` field added and initialized
- **`!loop` command handling**: `!loop start <spec-path>`, `!loop status`, `!loop abort <loop-id>`
- **Frozen harness enforcement** in both approval paths (stream-JSON and filesystem): Write/Edit file_path checked against `is_frozen()`, Bash command strings scanned for frozen path substrings; auto-denied with `FrozenHarnessViolation` log
- Budget composition TODO noted — `deduct_iteration_tokens()` API ready, pending BudgetTracker wiring

### Phase 6 — `agent.rs`

Added `build_loop_context(loop_info: Option<&loop_engine::ActiveLoop>) -> Option<String>`:
- Returns None when no active loop
- Formats loop constraint block for `--append-system-prompt` injection: loop ID, iteration N/max, objective, metric state, frozen/mutable path lists, per-iteration budget
- Doc comment added to `build_system_prompt()` marking the extension point

---

## Test Results

```
cargo test: 37 passed, 0 failed, 0 ignored
cargo check: 0 errors, 30 warnings (dead_code from not-yet-wired modules — expected)
```

New tests in `loop_engine.rs` (8 tests):
- spec_load_rejects_non_machine_readable_metric
- spec_load_rejects_empty_frozen_harness
- spec_load_valid
- iteration_lifecycle
- frozen_path_matching
- budget_exceeded_detection
- metric_improvement_higher_is_better
- metric_improvement_lower_is_better

---

## Deferred / Future Work

| Item | Reason deferred |
|------|----------------|
| Budget composition full wiring | BudgetTracker not yet in coordinator.rs dispatch loop |
| Loop state persistence to `loop_state_file` | Restart recovery for active loops |
| Metric extraction from Claude output | Needs structured output protocol in system prompt |
| Swarm loop type (multi-delegate) | Most complex loop type — requires N sub-delegate orchestration |
| `/loop complete` command | Manual completion path |

---

## Files Changed

| File | Change |
|------|--------|
| `coordinator/src/loop_engine.rs` | **Created** — 310 lines, 8 tests |
| `coordinator/src/main.rs` | Added `mod loop_engine;` |
| `coordinator/src/approval.rs` | +2 gate types, +8 test assertions |
| `coordinator/src/run_events.rs` | +6 event variants |
| `coordinator/src/config.rs` | +3 Settings fields + path expansion |
| `coordinator/src/coordinator.rs` | LoopManager integration, !loop commands, frozen harness enforcement |
| `coordinator/src/agent.rs` | `build_loop_context()` helper |
| `coordinator/Cargo.toml` | Added `tempfile = "3"` to dev-dependencies |

---

## Next Sprint Suggestions

1. **Wire budget composition** — connect `deduct_iteration_tokens()` to the existing BudgetTracker in the dispatch loop
2. **Loop state persistence** — serialize active loops to `loop_state_file` on change, reload on startup
3. **Metric extraction protocol** — define structured output format for loop agents; parse from `ClaudeResultMessage`
4. **First real Loop Spec** — write a researcher loop spec in `~/dev/autoresearch/loop-specs/` and run it end-to-end
5. **Swarm loop support** — multi-delegate sub-loop orchestration (future sprint)
