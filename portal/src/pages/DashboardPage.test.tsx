import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

function tasksDocument() {
  return {
    tasks: [],
    blocks: {
      unassigned: {
        label: "Unassigned",
        color: "#999"
      }
    },
    log: []
  };
}

describe("DashboardPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the active loops metric and strip when status feeds include active_loops", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.endsWith("/jobs.json")) {
          return new Response(JSON.stringify(tasksDocument()), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/approvals/pending")) {
          return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/budget/status")) {
          return new Response(JSON.stringify({ agents: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/status/boot.json")) {
          return new Response(
            JSON.stringify({
              status: "running",
              active_loops: [
                {
                  loop_id: "loop-1",
                  status: "running",
                  current_iteration: 2,
                  best_metric: 1.2345,
                  spec: {
                    loop_id: "loop-1",
                    name: "Research Loop",
                    loop_type: "researcher",
                    agent_id: "boot",
                    budget: {
                      per_iteration: "50000 tokens",
                      max_iterations: 10
                    },
                    approval_gate: "none"
                  }
                }
              ]
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (url.includes("/status/")) {
          return new Response(JSON.stringify({ status: "idle", active_loops: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );

    const queryClient = createTestQueryClient();
    render(<DashboardPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Active Loops").length).toBeGreaterThan(0);
    expect(screen.getByText("Research Loop")).toBeInTheDocument();
    expect(screen.getByText("Iter 2/10")).toBeInTheDocument();
  });

  it("defaults missing active_loops fields to the waiting loop state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.endsWith("/jobs.json")) {
          return new Response(JSON.stringify(tasksDocument()), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/approvals/pending")) {
          return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/budget/status")) {
          return new Response(JSON.stringify({ agents: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/status/")) {
          return new Response(JSON.stringify({ status: "idle" }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );

    const queryClient = createTestQueryClient();
    render(<DashboardPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.queryByText("Loops: awaiting status")).not.toBeInTheDocument();
  });
});
