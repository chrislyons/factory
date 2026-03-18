import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalyticsPage } from "./AnalyticsPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

vi.mock("../components/charts/ChartCanvas", () => ({
  ChartCanvas: () => <div data-testid="chart-canvas" />
}));

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("AnalyticsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders all chart scaffolds when analytics data is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not found", { status: 404 }))
    );

    const queryClient = createTestQueryClient();
    render(<AnalyticsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("Run Activity")).toBeInTheDocument();
    expect(screen.getByText("Tasks by Status")).toBeInTheDocument();
    expect(screen.getByText("Tasks by Assignee")).toBeInTheDocument();
    expect(screen.getByText("Approval Rate")).toBeInTheDocument();
    expect(screen.getByText("Run activity appears here when analytics summary is available.")).toBeInTheDocument();
  });

  it("renders live chart canvases when analytics data is present", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          run_activity: [
            { label: "Mon", succeeded: 2, failed: 1, other: 0 },
            { label: "Tue", succeeded: 3, failed: 0, other: 1 }
          ],
          tasks_by_status: [
            { label: "Mon", todo: 1, in_progress: 2, done: 1, blocked: 0 },
            { label: "Tue", todo: 0, in_progress: 1, done: 3, blocked: 1 }
          ],
          tasks_by_assignee: [
            { label: "Boot", value: 2 },
            { label: "IG-88", value: 1 }
          ],
          approval_rate: { approved: 3, rejected: 1, timed_out: 0 }
        })
      )
    );

    const queryClient = createTestQueryClient();
    render(<AnalyticsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByTestId("chart-canvas")).toHaveLength(4);
  });
});
