import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalyticsPage } from "./AnalyticsPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

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

  it("renders overview cards and section headings", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not found", { status: 404 }))
    );

    const queryClient = createTestQueryClient();
    const { container } = render(<AnalyticsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));

    // Check h1 title
    expect(screen.getByRole("heading", { level: 1, name: "Stats" })).toBeInTheDocument();

    // Check overview card labels exist in DOM (use container to avoid strict-mode duplicates)
    expect(container.querySelectorAll(".stats-overview-card__label")).toHaveLength(4);

    // Check section headings exist (at least one of each)
    const sectionTitles = Array.from(container.querySelectorAll(".surface-card h2")).map(
      (el) => el.textContent
    );
    expect(sectionTitles).toContain("Agent Roster");
    expect(sectionTitles).toContain("Memory & Inference");
    expect(sectionTitles).toContain("Tasks by Status");
    expect(sectionTitles).toContain("Tasks by Assignee");
    expect(sectionTitles).toContain("Budget");
  });

  it("renders agent cards when config data is available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const path = typeof url === "string" ? url : "";
        if (path.includes("/api/config") && !path.includes("memory-budget")) {
          return jsonResponse({
            agents: [
              {
                id: "boot",
                label: "Boot",
                model: "gemma-4-e4b-it-6bit",
                provider: "mlx-vlm:41961",
                toolsets: ["terminal", "file", "web"]
              },
              {
                id: "ig88",
                label: "IG-88",
                model: "xiaomi/mimo-v2-pro",
                provider: "nous",
                toolsets: ["terminal", "file"]
              }
            ]
          });
        }
        if (path.includes("memory-budget")) {
          return jsonResponse({
            total_gb: 32.0,
            available_gb: 8.5,
            used_by_inference_gb: 7.3,
            headroom_gb: 1.2,
            models: [
              { agent: "boot", provider: "mlx-vlm:41961", port: 41961, model: "gemma-4-e4b-it-6bit", loaded: true, est_gb: 7.3 }
            ]
          });
        }
        if (path.includes("/jobs.json")) {
          return jsonResponse({
            tasks: [
              { id: "1", title: "Test", status: "pending", order: 0, blocked_by: [], block: "A" },
              { id: "2", title: "Done", status: "done", order: 1, blocked_by: [], block: "A" }
            ],
            blocks: {},
            log: []
          });
        }
        if (path.includes("/budget/")) {
          return jsonResponse({ agents: [] });
        }
        return new Response("not found", { status: 404 });
      })
    );

    const queryClient = createTestQueryClient();
    const { container } = render(<AnalyticsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));

    // Agent cards should be rendered
    const agentCards = container.querySelectorAll(".stats-agent-card");
    expect(agentCards.length).toBeGreaterThanOrEqual(2);
  });
});
