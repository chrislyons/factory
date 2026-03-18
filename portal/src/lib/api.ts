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

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(`HTTP ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}

export async function fetchJson<T>(input: string, init?: RequestInit) {
  const response = await fetch(input, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  return parseResponse<T>(response);
}

export async function fetchTasks() {
  return fetchJson<TasksDocument>("/tasks.json");
}

export async function saveTasks(document: TasksDocument) {
  return fetchJson<TasksDocument>("/tasks.json", {
    method: "PUT",
    body: JSON.stringify(document, null, 2)
  });
}

export async function fetchAgentStatus(agentId: AgentId) {
  return fetchJson<AgentStatus>(`/status/${agentId}.json`);
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
