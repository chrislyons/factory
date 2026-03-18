import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PortalPage } from "./PortalPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("PortalPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the operator utility panels visible when coordinator routes are unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not found", { status: 404 }))
    );

    const queryClient = createTestQueryClient();
    render(<PortalPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("Operator Flow")).toBeInTheDocument();
    expect(screen.getByText("Shared Signals")).toBeInTheDocument();
    expect(screen.queryByText(/active agents/i)).not.toBeInTheDocument();
  });

  it("renders live landing-card badges when portal metrics are available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes("/approvals/pending")) {
          return jsonResponse([{ id: "approval-1" }]);
        }
        if (url.includes("/budget/status")) {
          return jsonResponse({
            agents: [
              {
                agent_id: "boot",
                monthly_limit_usd: 100,
                spent_this_month_usd: 12,
                status: { kind: "paused", reason: "limit reached" },
                incidents: []
              }
            ]
          });
        }
        if (url.includes("/status/boot.json")) {
          return jsonResponse({
            status: "running",
            active_loops: [
              {
                loop_id: "loop-1"
              }
            ]
          });
        }
        if (url.includes("/status/ig88.json")) {
          return jsonResponse({ status: "idle", active_loops: [] });
        }
        if (url.includes("/status/")) {
          return jsonResponse({ status: "paused", active_loops: [] });
        }
        return jsonResponse([]);
      })
    );

    const queryClient = createTestQueryClient();
    render(<PortalPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("2 active agents")).toBeInTheDocument();
    expect(screen.getByText("1 pending")).toBeInTheDocument();
    expect(screen.getByText("1 paused")).toBeInTheDocument();
  });
});
