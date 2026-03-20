export type AgentId = "boot" | "ig88" | "kelk" | "nan";

export type ApprovalGateType =
  | "tool_call"
  | "trading_execution"
  | "agent_elevation"
  | "loop_spec_deploy"
  | "budget_override"
  | "loop_iteration"
  | "infra_change";

export type ApprovalDecisionInput = "approve" | "reject";

export type RunEventType =
  | "tool_call"
  | "tool_result"
  | "checkpoint"
  | "error"
  | "session_start"
  | "session_end"
  | "loop_start"
  | "iteration_start"
  | "iteration_end"
  | "loop_complete"
  | "loop_aborted"
  | "frozen_harness_violation";

export type EventStream = "system" | "stdout" | "stderr";
export type EventLevel = "info" | "warn" | "error";
export type ThresholdType = "soft" | "hard";
export type IncidentStatus = "open" | "resolved" | "dismissed";
export type LoopType = "researcher" | "narrative" | "infra_improve" | "coding" | "swarm";
export type MetricDirection = "higher_is_better" | "lower_is_better";
export type RollbackMethod = "git_reset" | "config_revert" | "file_delete" | "timer_cancel";
export type LoopApprovalGate =
  | "none"
  | "propose_then_execute"
  | "human_approval_required";
export type LoopStatus = "pending" | "running" | "paused" | "completed" | "aborted";

export interface TaskRecord {
  id: string;
  title: string;
  description?: string;
  status: "pending" | "in-progress" | "done" | "blocked";
  effort?: string;
  order: number;
  blocked_by: string[];
  block: string;
  assignee?: string | null;
  created?: string;
  updated?: string;
  domain?: string;
  job_class?: string;
  legacy_id?: string;
}

export interface TaskBlock {
  label: string;
  color: string;
}

export interface TaskLogEntry {
  timestamp: string;
  actor: string;
  action: string;
  task_id?: string;
  detail?: string;
}

export interface TasksDocument {
  tasks: TaskRecord[];
  blocks: Record<string, TaskBlock>;
  log: TaskLogEntry[];
  updated?: string;
  updated_by?: string;
}

export interface CurrentRunTailEntry {
  seq: number;
  message: string;
  event_type: RunEventType | string;
}

export interface CurrentRunSummary {
  run_id: string;
  started_at: string;
  status: string;
  transcript_tail: CurrentRunTailEntry[];
  finished_at?: string | null;
}

export interface LoopMetric {
  name: string;
  formula: string;
  baseline: number;
  direction: MetricDirection;
  machine_readable: boolean;
}

export interface LoopBudget {
  per_iteration: string;
  max_iterations: number;
}

export interface RollbackMechanism {
  method: RollbackMethod;
  command: string;
  scope: string;
}

export interface LoopSpec {
  loop_id: string;
  name: string;
  objective: string;
  loop_type: LoopType;
  agent_id: string;
  metric: LoopMetric;
  frozen_harness: string[];
  mutable_surface: string[];
  budget: LoopBudget;
  rollback: RollbackMechanism;
  approval_gate: LoopApprovalGate;
  worker_cwd?: string | null;
}

export type LoopSpecSummary = Pick<
  LoopSpec,
  "loop_id" | "name" | "loop_type" | "agent_id" | "budget" | "approval_gate"
>;

export interface IterationRecord {
  iteration: number;
  metric_value: number;
  delta: number;
  tokens_used: number;
  kept: boolean;
  started_at: string;
  ended_at: string;
}

export interface StatusActiveLoop {
  loop_id: string;
  status: LoopStatus | string;
  current_iteration: number;
  best_metric?: number | null;
  spec: LoopSpecSummary;
}

export interface ActiveLoop {
  loop_id: string;
  spec: LoopSpec;
  status: LoopStatus | string;
  current_iteration: number;
  iteration_tokens_used: number;
  total_tokens_used: number;
  best_metric?: number | null;
  iterations: IterationRecord[];
}

export interface AgentStatus {
  status?: string;
  notes?: string;
  current_task?: string;
  last_updated?: string;
  current_run?: CurrentRunSummary | null;
  active_loops?: StatusActiveLoop[];
  [key: string]: unknown;
}

export interface PendingApproval {
  id: string;
  gate_type: ApprovalGateType;
  agent_name: string;
  tool_name?: string;
  payload?: Record<string, unknown> | null;
  requested_at: string;
  timeout_ms: number;
}

export interface ResolvedApproval extends PendingApproval {
  decision: "approved" | "rejected" | "timed_out";
  resolved_at?: string;
}

export interface BudgetIncident {
  id: string;
  agent_id: string;
  threshold_type: ThresholdType;
  amount_limit: number;
  amount_observed: number;
  status: IncidentStatus;
  created_at: string;
  resolved_at?: string | null;
}

export type BudgetStatusSummary =
  | { kind: "normal" }
  | { kind: "warning"; pct: number }
  | { kind: "paused"; reason: string };

export interface AgentBudgetStatus {
  agent_id: string;
  monthly_limit_usd: number;
  spent_this_month_usd: number;
  status: BudgetStatusSummary | string;
  incidents: BudgetIncident[];
  runtime_state?: AgentRuntimeState | null;
}

export interface BudgetStatusResponse {
  agents: AgentBudgetStatus[];
}

export interface AgentRuntimeState {
  agent_id: string;
  session_id?: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_cents: number;
  last_run_status: string;
  last_error?: string | null;
  updated_at: string;
}

export interface AnalyticsSeriesPoint {
  label: string;
  succeeded?: number;
  failed?: number;
  other?: number;
  todo?: number;
  in_progress?: number;
  done?: number;
  blocked?: number;
}

export interface AnalyticsSummary {
  run_activity: AnalyticsSeriesPoint[];
  tasks_by_status: AnalyticsSeriesPoint[];
  tasks_by_assignee: { label: string; value: number }[];
  approval_rate: { approved: number; rejected: number; timed_out: number };
}

export interface RunEvent {
  run_id: string;
  seq: number;
  event_type: RunEventType | string;
  stream: EventStream | string;
  level: EventLevel | string;
  message: string;
  payload?: Record<string, unknown> | null;
  timestamp: string;
}

export interface AgentDetailSummary {
  agent_id: string;
  name: string;
  model?: string;
  trust_level?: string;
  context_mode?: string;
  status?: string;
  runtime_state?: AgentRuntimeState | null;
  budget?: AgentBudgetStatus | null;
  config?: Record<string, unknown> | null;
  current_run?: CurrentRunSummary | null;
  loops?: ActiveLoop[];
}

export interface AgentRunRecord {
  id: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  task?: string | null;
  cost_cents?: number | null;
}

export interface AgentDetailResponse {
  agent: AgentDetailSummary;
  runs: AgentRunRecord[];
}
