import { useMemo } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseQueryResult
} from "@tanstack/react-query";
import {
  abortLoop,
  cancelRun,
  decideApproval,
  fetchAgentDetail,
  fetchAgentStatus,
  fetchAnalyticsSummary,
  fetchBudgetStatus,
  fetchConfigSummaries,
  fetchLoopDetail,
  fetchLoops,
  fetchMemoryBudget,
  fetchPendingApprovals,
  fetchResolvedApprovals,
  fetchRunEvents,
  fetchTasks,
  requestBudgetOverride,
  saveTasks,
  startLoop,
  triggerAgentAction
} from "../lib/api";
import { AGENTS, POLL_INTERVAL_MS } from "../lib/constants";
import type {
  ActiveLoop,
  AgentDetailResponse,
  AgentId,
  AgentStatus,
  AnalyticsSummary,
  ApprovalDecisionInput,
  PendingApproval,
  ResolvedApproval,
  RunEvent,
  TasksDocument
} from "../lib/types";

function pollingOptions<T>(queryFn: () => Promise<T>) {
  return {
    queryFn,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 2_000,
    placeholderData: (previousData: T | undefined) => previousData
  };
}

export function useTasksDocument() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["tasks-document"],
    ...pollingOptions(fetchTasks)
  });

  const saveMutation = useMutation({
    mutationFn: saveTasks
  });

  async function updateDocument(updater: (current: TasksDocument) => TasksDocument) {
    const current = queryClient.getQueryData<TasksDocument>(["tasks-document"]) ?? query.data;
    if (!current) return;
    const next = updater(current);
    queryClient.setQueryData(["tasks-document"], next);
    try {
      await saveMutation.mutateAsync(next);
    } catch (error) {
      queryClient.setQueryData(["tasks-document"], current);
      throw error;
    }
  }

  return {
    ...query,
    saveMutation,
    updateDocument
  };
}

export function useAgentStatuses() {
  const results = useQueries({
    queries: AGENTS.map((agent) => ({
      queryKey: ["agent-status", agent.id],
      ...pollingOptions(() => fetchAgentStatus(agent.id))
    }))
  });

  return useMemo(() => {
    const map: Partial<Record<AgentId, AgentStatus>> = {};
    let latestUpdate = 0;
    let hasError = false;

    results.forEach((result, index) => {
      const agent = AGENTS[index];
      if (result.data) {
        map[agent.id] = result.data;
      }
      if (result.error) {
        hasError = true;
      }
      latestUpdate = Math.max(latestUpdate, result.dataUpdatedAt || 0);
    });

    return {
      data: map,
      results,
      isLoading: results.every((result) => result.isLoading),
      isFetching: results.some((result) => result.isFetching),
      hasError,
      dataUpdatedAt: latestUpdate
    };
  }, [results]);
}

export function usePendingApprovals() {
  return useQuery({
    queryKey: ["approvals", "pending"],
    ...pollingOptions(fetchPendingApprovals)
  });
}

export function useResolvedApprovals() {
  return useQuery({
    queryKey: ["approvals", "resolved"],
    ...pollingOptions(fetchResolvedApprovals)
  });
}

export function useApprovalDecision() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: ApprovalDecisionInput }) =>
      decideApproval(id, decision),
    onMutate: async ({ id, decision }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["approvals", "pending"] }),
        queryClient.cancelQueries({ queryKey: ["approvals", "resolved"] })
      ]);

      const previousPending =
        queryClient.getQueryData<PendingApproval[]>(["approvals", "pending"]) ?? [];
      const previousResolved =
        queryClient.getQueryData<ResolvedApproval[]>(["approvals", "resolved"]) ?? [];
      const approval = previousPending.find((item) => item.id === id);

      queryClient.setQueryData(
        ["approvals", "pending"],
        previousPending.filter((item) => item.id !== id)
      );

      if (approval) {
        queryClient.setQueryData<ResolvedApproval[]>(["approvals", "resolved"], [
          {
            ...approval,
            decision: decision === "approve" ? "approved" : "rejected",
            resolved_at: new Date().toISOString()
          },
          ...previousResolved
        ]);
      }

      return { previousPending, previousResolved };
    },
    onError: (_error, _variables, context) => {
      if (!context) return;
      queryClient.setQueryData(["approvals", "pending"], context.previousPending);
      queryClient.setQueryData(["approvals", "resolved"], context.previousResolved);
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["approvals", "pending"] }),
        queryClient.invalidateQueries({ queryKey: ["approvals", "resolved"] })
      ]);
    }
  });
}

export function useBudgetStatus() {
  return useQuery({
    queryKey: ["budget-status"],
    ...pollingOptions(fetchBudgetStatus)
  });
}

export function useBudgetOverride() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: requestBudgetOverride,
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["approvals", "pending"] });
    }
  });
}

export function useAnalytics(days = 14) {
  return useQuery({
    queryKey: ["analytics", days],
    queryFn: () => fetchAnalyticsSummary(days),
    refetchInterval: POLL_INTERVAL_MS * 2,
    placeholderData: (previousData: AnalyticsSummary | undefined) => previousData
  });
}

export function useAgentDetail(agentId: AgentId) {
  return useQuery({
    queryKey: ["agent-detail", agentId],
    queryFn: () => fetchAgentDetail(agentId),
    refetchInterval: POLL_INTERVAL_MS,
    placeholderData: (previousData: AgentDetailResponse | undefined) => previousData
  });
}

export function useRunEvents(runId?: string | null) {
  return useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => fetchRunEvents(runId ?? ""),
    enabled: Boolean(runId),
    refetchInterval: POLL_INTERVAL_MS,
    placeholderData: (previousData: RunEvent[] | undefined) => previousData
  });
}

export function useLoops() {
  return useQuery({
    queryKey: ["loops"],
    ...pollingOptions(fetchLoops)
  });
}

export function useLoopDetail(loopId?: string | null) {
  return useQuery({
    queryKey: ["loops", loopId],
    queryFn: () => fetchLoopDetail(loopId ?? ""),
    enabled: Boolean(loopId),
    refetchInterval: POLL_INTERVAL_MS,
    placeholderData: (previousData: ActiveLoop | undefined) => previousData
  });
}

export function useLoopStart() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startLoop,
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["loops"] }),
        queryClient.invalidateQueries({ queryKey: ["agent-status"] })
      ]);
    }
  });
}

export function useLoopAbort() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: abortLoop,
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["loops"] }),
        queryClient.invalidateQueries({ queryKey: ["agent-status"] }),
        queryClient.invalidateQueries({ queryKey: ["agent-detail"] })
      ]);
    }
  });
}

export function useRunCancel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: cancelRun,
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agent-detail"] }),
        queryClient.invalidateQueries({ queryKey: ["agent-status"] })
      ]);
    }
  });
}

export function useAgentAction(agentId: AgentId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: "pause" | "resume" | "heartbeat") => triggerAgentAction(agentId, action),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agent-detail", agentId] }),
        queryClient.invalidateQueries({ queryKey: ["agent-status", agentId] })
      ]);
    }
  });
}

export function latestDataUpdatedAt(results: Array<UseQueryResult<unknown, Error>>) {
  return results.reduce((latest, result) => Math.max(latest, result.dataUpdatedAt || 0), 0);
}

export function useConfigSummaries() {
  return useQuery({
    queryKey: ["config-summaries"],
    ...pollingOptions(fetchConfigSummaries)
  });
}

export function useMemoryBudget() {
  return useQuery({
    queryKey: ["memory-budget"],
    queryFn: fetchMemoryBudget,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 3_000,
    placeholderData: (previousData) => previousData
  });
}

export function useFactoryStats() {
  const config = useConfigSummaries();
  const memory = useMemoryBudget();
  const budget = useBudgetStatus();

  return {
    config,
    memory,
    budget,
    isLoading: config.isLoading || memory.isLoading,
    dataUpdatedAt: Math.max(
      config.dataUpdatedAt || 0,
      memory.dataUpdatedAt || 0,
      budget.dataUpdatedAt || 0
    ),
    hasError: Boolean(config.error || memory.error)
  };
}
