import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BudgetPage } from "./BudgetPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("BudgetPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows compact degraded budget states when coordinator routes are unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not found", { status: 404 }))
    );

    const queryClient = createTestQueryClient();
    render(<BudgetPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("Waiting for coordinator budget status")).toBeInTheDocument();
  });

  it("renders budget policy cards when spend data is available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          agents: [
            {
              agent_id: "boot",
              monthly_limit_usd: 100,
              spent_this_month_usd: 80,
              status: { kind: "warning", pct: 80 },
              incidents: []
            },
            {
              agent_id: "ig88",
              monthly_limit_usd: 100,
              spent_this_month_usd: 120,
              status: { kind: "paused", reason: "limit reached" },
              incidents: [
                {
                  id: "incident-1",
                  agent_id: "ig88",
                  threshold_type: "hard_stop",
                  amount_limit: 100,
                  amount_observed: 120,
                  status: "open",
                  created_at: "2026-03-17T12:00:00Z"
                }
              ]
            }
          ]
        })
      )
    );

    const queryClient = createTestQueryClient();
    render(<BudgetPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Request Override").length).toBe(2);
    expect(screen.getByText("Budget exhausted — agent paused")).toBeInTheDocument();
    expect(screen.getByText("hard_stop")).toBeInTheDocument();
  });
});
