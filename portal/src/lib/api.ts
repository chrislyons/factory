import { z } from "zod";
import type {
  ActiveLoop,
  AgentBudgetStatus,
  AgentDetailResponse,
  AgentId,
  AgentStatus,
  AnalyticsSummary,
  ApprovalDecisionInput,
  PendingApproval,
  ResolvedApproval,
  RunEvent,
  TasksDocument
} from "./types";

const TaskRecordSchema = z.object({
  id: z.string(),
  title: z.string(),
  status: z.string(),
  order: z.number(),
  blocked_by: z.array(z.string()),
  block: z.string(),
}).passthrough();

const TasksDocumentSchema = z.object({
  tasks: z.array(TaskRecordSchema),
  blocks: z.record(z.string(), z.object({ label: z.string(), color: z.string() })),
  log: z.array(z.object({ timestamp: z.string(), actor: z.string(), action: z.string() }).passthrough()),
}).passthrough();

const AgentStatusSchema = z.object({}).passthrough();

const OkResponseSchema = z.object({ ok: z.literal(true) });

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)factory_csrf=([^;]+)/);
  return match?.[1] ?? "";
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    const here = window.location.pathname + window.location.search;
    window.location.assign(`/pages/login.html?redirect=${encodeURIComponent(here)}`);
    return new Promise(() => {});  // never resolves — navigation is underway
  }
  if (!response.ok) {
    throw new ApiError(`HTTP ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}

export async function fetchJson<T>(input: string, init?: RequestInit) {
  const method = init?.method?.toUpperCase() ?? "GET";
  const csrfHeaders: Record<string, string> =
    method === "POST" || method === "PUT" || method === "DELETE" || method === "PATCH"
      ? { "X-CSRF-Token": getCsrfToken() }
      : {};

  const response = await fetch(input, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...csrfHeaders,
      ...(init?.headers ?? {})
    }
  });
  return parseResponse<T>(response);
}

export async function fetchTasks() {
  const data = await fetchJson<TasksDocument>("/jobs.json");
  return TasksDocumentSchema.parse(data) as TasksDocument;
}

export async function saveTasks(document: TasksDocument) {
  const data = await fetchJson<TasksDocument>("/jobs.json", {
    method: "PUT",
    body: JSON.stringify(document, null, 2)
  });
  return data;
}

export async function fetchAgentStatus(agentId: AgentId) {
  const data = await fetchJson<AgentStatus>(`/status/${agentId}.json`);
  return AgentStatusSchema.parse(data) as AgentStatus;
}

export async function fetchPendingApprovals() {
  return fetchJson<PendingApproval[]>("/approvals/pending");
}

export async function decideApproval(approvalId: string, decision: ApprovalDecisionInput) {
  return fetchJson<{ ok: true }>(`/approvals/${approvalId}/decide`, {
    method: "POST",
    body: JSON.stringify({ decision })
  });
}

export async function fetchResolvedApprovals() {
  return fetchJson<ResolvedApproval[]>("/approvals/resolved?limit=20");
}

export async function fetchBudgetStatus() {
  return fetchJson<{ agents: AgentBudgetStatus[] }>("/budget/status");
}

export async function requestBudgetOverride(agentId: AgentId) {
  return fetchJson<{ ok: true }>(`/approvals/budget-override`, {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId })
  });
}

export async function fetchAnalyticsSummary(days = 14) {
  return fetchJson<AnalyticsSummary>(`/analytics/summary?days=${days}`);
}

export async function cancelRun(runId: string) {
  return fetchJson<{ ok: true }>(`/runs/${runId}/cancel`, { method: "POST" });
}

export async function triggerAgentAction(agentId: AgentId, action: "pause" | "resume" | "heartbeat") {
  return fetchJson<{ ok: true }>(`/agents/${agentId}/${action}`, { method: "POST" });
}

export async function fetchAgentDetail(agentId: AgentId) {
  return fetchJson<AgentDetailResponse>(`/agents/${agentId}`);
}

export async function fetchRunEvents(runId: string) {
  return fetchJson<RunEvent[]>(`/runs/${runId}/events`);
}

export async function fetchLoops() {
  return fetchJson<ActiveLoop[]>("/loops");
}

export async function fetchLoopDetail(loopId: string) {
  return fetchJson<ActiveLoop>(`/loops/${loopId}`);
}

export async function startLoop(specPath: string) {
  return fetchJson<{ ok: true; loop_id?: string }>(`/loops/start`, {
    method: "POST",
    body: JSON.stringify({ spec_path: specPath })
  });
}

export async function abortLoop(loopId: string) {
  return fetchJson<{ ok: true }>(`/loops/${loopId}/abort`, {
    method: "POST"
  });
}

// ─── Config API (Hermes agent config management) ─────────────────────────

export interface AgentConfigSummary {
  id: string;
  label: string;
  model?: string;
  provider?: string;
  base_url?: string;
  display?: {
    compact?: boolean;
    streaming?: boolean;
    show_cost?: boolean;
    show_reasoning?: boolean;
  };
  max_turns?: number;
  max_tokens?: number;
  tool_use_enforcement?: string;
  approval_mode?: string;
  toolsets?: string[];
  error?: string;
}

export interface AgentHealth {
  reachable: boolean;
  url: string | null;
  status: number | null;
  error: string | null;
}

export interface ConfigListResponse {
  agents: AgentConfigSummary[];
}

export interface ConfigDetailResponse {
  agent: string;
  config: Record<string, unknown>;
  health: AgentHealth;
}

export interface ConfigPatchResponse {
  ok: boolean;
  agent: string;
  updated_fields: string[];
  config: Record<string, unknown>;
}

export async function fetchConfigSummaries() {
  return fetchJson<ConfigListResponse>("/api/config");
}

export async function fetchAgentConfig(agentId: string) {
  return fetchJson<ConfigDetailResponse>(`/api/config/${agentId}`);
}

export async function patchAgentConfig(agentId: string, patch: Record<string, unknown>) {
  return fetchJson<ConfigPatchResponse>(`/api/config/${agentId}`, {
    method: "PATCH",
    body: JSON.stringify(patch)
  });
}

export async function fetchAgentHealth(agentId: string) {
  return fetchJson<AgentHealth>(`/api/config/${agentId}/health`);
}

export async function restartAgentGateway(agentId: string) {
  return fetchJson<{ ok: boolean; agent?: string; label?: string; error?: string }>(
    `/api/config/${agentId}/restart`,
    { method: "POST" }
  );
}
