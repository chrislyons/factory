import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApprovalsPage } from "./ApprovalsPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

describe("ApprovalsPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes("/approvals/pending") || url.includes("/approvals/resolved")) {
          return new Response("not found", { status: 404 });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows waiting states when coordinator approval endpoints are unavailable", async () => {
    const queryClient = createTestQueryClient();

    await act(async () => {
      render(<ApprovalsPage />, {
        wrapper: createQueryClientWrapper(queryClient)
      });
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("No pending approvals")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for coordinator…").length).toBeGreaterThan(0);
  });

  it("renders loop-specific approval gate labels from coordinator-rs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes("/approvals/pending")) {
          return new Response(
            JSON.stringify([
              {
                id: "loop-approval",
                gate_type: "loop_iteration",
                agent_name: "Boot",
                requested_at: "2026-03-17T12:00:00Z",
                timeout_ms: 300000,
                payload: { loop_id: "loop-1" }
              },
              {
                id: "infra-approval",
                gate_type: "infra_change",
                agent_name: "Boot",
                requested_at: "2026-03-17T12:00:00Z",
                timeout_ms: 3600000,
                payload: { loop_id: "loop-2" }
              }
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (url.includes("/approvals/resolved")) {
          return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );

    const queryClient = createTestQueryClient();
    render(<ApprovalsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Loop Iteration").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Infra Change").length).toBeGreaterThan(0);
  });
});
