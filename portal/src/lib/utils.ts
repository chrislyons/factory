import { AGENTS } from "./constants";
import type {
  AgentId,
  ApprovalGateType,
  BudgetStatusSummary,
  LoopApprovalGate,
  LoopStatus,
  LoopType,
  RollbackMethod,
  RunEventType
} from "./types";

export function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value < 100 ? 2 : 0
  }).format(value);
}

export function formatCents(value: number) {
  return formatUsd(value / 100);
}

export function timeAgo(input?: string | null) {
  if (!input) return "Unknown";
  const timestamp = new Date(input).getTime();
  if (Number.isNaN(timestamp)) return "Unknown";
  const deltaSeconds = Math.round((timestamp - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
    ["second", 1]
  ];

  for (const [unit, size] of units) {
    if (Math.abs(deltaSeconds) >= size || unit === "second") {
      return rtf.format(Math.trunc(deltaSeconds / size), unit);
    }
  }

  return "just now";
}

export function relativeTimestamp(input?: string | null) {
  if (!input) return "No timestamp";
  return `${new Date(input).toLocaleString()} · ${timeAgo(input)}`;
}

export function approvalGateLabel(gate: ApprovalGateType) {
  const labels: Record<ApprovalGateType, string> = {
    tool_call: "Tool Call",
    trading_execution: "Trading Execution",
    agent_elevation: "Agent Elevation",
    loop_spec_deploy: "Loop Spec Deploy",
    budget_override: "Budget Override",
    loop_iteration: "Loop Iteration",
    infra_change: "Infra Change"
  };
  return labels[gate];
}

export function approvalGateColor(gate: ApprovalGateType) {
  const colors: Record<ApprovalGateType, string> = {
    tool_call: "var(--pill-gray)",
    trading_execution: "var(--yellow)",
    agent_elevation: "var(--purple)",
    loop_spec_deploy: "var(--accent)",
    budget_override: "var(--red)",
    loop_iteration: "var(--blue)",
    infra_change: "var(--red)"
  };
  return colors[gate];
}

export function loopTypeLabel(loopType: LoopType | string) {
  const labels: Record<LoopType, string> = {
    researcher: "Researcher",
    narrative: "Narrative",
    infra_improve: "Infra Improve",
    coding: "Coding",
    swarm: "Swarm"
  };
  return labels[loopType as LoopType] ?? loopType.replace(/_/g, " ");
}

export function loopApprovalGateLabel(gate: LoopApprovalGate | string) {
  const labels: Record<LoopApprovalGate, string> = {
    none: "No Approval",
    propose_then_execute: "Propose Then Execute",
    human_approval_required: "Human Approval Required"
  };
  return labels[gate as LoopApprovalGate] ?? gate.replace(/_/g, " ");
}

export function rollbackMethodLabel(method: RollbackMethod | string) {
  const labels: Record<RollbackMethod, string> = {
    git_reset: "Git Reset",
    config_revert: "Config Revert",
    file_delete: "File Delete",
    timer_cancel: "Timer Cancel"
  };
  return labels[method as RollbackMethod] ?? method.replace(/_/g, " ");
}

export function loopStatusLabel(status: LoopStatus | string) {
  const labels: Record<LoopStatus, string> = {
    pending: "Pending",
    running: "Running",
    paused: "Paused",
    completed: "Completed",
    aborted: "Aborted"
  };
  return labels[status as LoopStatus] ?? status.replace(/_/g, " ");
}

export function loopStatusTone(status: LoopStatus | string) {
  if (status === "running") return "is-running";
  if (status === "paused") return "is-paused";
  if (status === "completed") return "is-completed";
  if (status === "aborted") return "is-aborted";
  return "is-pending";
}

export function runEventLabel(eventType: RunEventType | string) {
  const labels: Record<RunEventType, string> = {
    tool_call: "Tool Call",
    tool_result: "Tool Result",
    checkpoint: "Checkpoint",
    error: "Error",
    session_start: "Session Start",
    session_end: "Session End",
    loop_start: "Loop Start",
    iteration_start: "Iteration Start",
    iteration_end: "Iteration End",
    loop_complete: "Loop Complete",
    loop_aborted: "Loop Aborted",
    frozen_harness_violation: "Frozen Harness Violation"
  };
  return labels[eventType as RunEventType] ?? eventType.replace(/_/g, " ");
}

export function formatMetricValue(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1000) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(2);
  return value.toFixed(4);
}

export function agentDefinition(agentId?: string | null) {
  return AGENTS.find((agent) => agent.id === (agentId ?? "").toLowerCase() as AgentId) ?? null;
}

export function budgetStatusKind(input: BudgetStatusSummary | string): "normal" | "warning" | "paused" {
  if (typeof input === "string") {
    const normalized = input.toLowerCase();
    if (normalized.includes("pause")) return "paused";
    if (normalized.includes("warn")) return "warning";
    return "normal";
  }
  return input.kind;
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
