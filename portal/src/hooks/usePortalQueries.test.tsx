import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PendingApproval, ResolvedApproval } from "../lib/types";
import { decideApproval } from "../lib/api";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";
import { useApprovalDecision } from "./usePortalQueries";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    decideApproval: vi.fn()
  };
});

const mockedDecideApproval = vi.mocked(decideApproval);

function makeApproval(id: string): PendingApproval {
  return {
    id,
    gate_type: "tool_call",
    agent_name: "Boot",
    payload: { tool: "deploy" },
    requested_at: "2026-03-17T12:00:00Z",
    timeout_ms: 60_000,
    tool_name: "deploy"
  };
}

describe("useApprovalDecision", () => {
  afterEach(() => {
    mockedDecideApproval.mockReset();
  });

  it("moves approvals into resolved history optimistically", async () => {
    mockedDecideApproval.mockResolvedValue({ ok: true });

    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["approvals", "pending"], [makeApproval("approval-1")]);
    queryClient.setQueryData(["approvals", "resolved"], []);

    const { result } = renderHook(() => useApprovalDecision(), {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await act(async () => {
      await result.current.mutateAsync({ id: "approval-1", decision: "approve" });
    });

    expect(queryClient.getQueryData(["approvals", "pending"])).toEqual([]);
    expect((queryClient.getQueryData(["approvals", "resolved"]) as ResolvedApproval[])[0]).toMatchObject({
      id: "approval-1",
      decision: "approved"
    });
  });

  it("rolls cache changes back when the coordinator rejects the decision", async () => {
    mockedDecideApproval.mockRejectedValue(new Error("boom"));

    const queryClient = createTestQueryClient();
    const pending = [makeApproval("approval-2")];
    queryClient.setQueryData(["approvals", "pending"], pending);
    queryClient.setQueryData(["approvals", "resolved"], []);

    const { result } = renderHook(() => useApprovalDecision(), {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await expect(
      act(async () => {
        await result.current.mutateAsync({ id: "approval-2", decision: "reject" });
      })
    ).rejects.toThrow("boom");

    expect(queryClient.getQueryData(["approvals", "pending"])).toEqual(pending);
    expect(queryClient.getQueryData(["approvals", "resolved"])).toEqual([]);
  });
});
