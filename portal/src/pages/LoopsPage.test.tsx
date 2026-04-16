import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoopsPage } from "./LoopsPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

describe("LoopsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockEndpoints(data: Record<string, unknown>) {
    return vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      for (const [key, value] of Object.entries(data)) {
        if (url.includes(key)) {
          return new Response(JSON.stringify(value), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
  }

  const emptyEndpoints = mockEndpoints({
    "/api/config/sessions": { active: [], completed: [], total: 0, tool_distribution: {} },
    "/api/config/cron-jobs": { jobs: [], count: 0 },
    "/api/config/rl-runs": {
      configured: false,
      has_tinker_key: false,
      has_wandb_key: false,
      tinker_atropos_exists: false,
      runs: [],
      run_count: 0,
    },
  });

  it("renders sessions, cron, and RL panels", async () => {
    vi.stubGlobal("fetch", emptyEndpoints);
    const queryClient = createTestQueryClient();
    render(<LoopsPage />, {
      wrapper: createQueryClientWrapper(queryClient),
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Hermes Sessions").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Cron Jobs").length).toBeGreaterThan(0);
    expect(screen.getAllByText("RL Training (GRPO)").length).toBeGreaterThan(0);
  });

  it("shows empty states for all three panels", async () => {
    vi.stubGlobal("fetch", emptyEndpoints);
    const queryClient = createTestQueryClient();
    render(<LoopsPage />, {
      wrapper: createQueryClientWrapper(queryClient),
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("No sessions found").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No cron jobs").length).toBeGreaterThan(0);
  });

  it("renders with session data", async () => {
    vi.stubGlobal(
      "fetch",
      mockEndpoints({
        "/api/config/sessions": {
          active: [
            {
              id: "test-session-1",
              source: "cli",
              user_id: null,
              model: "xiaomi/mimo-v2-pro",
              started_at: "2026-04-15T16:54:30+00:00",
              ended_at: null,
              message_count: 100,
              tool_call_count: 25,
              input_tokens: 50000,
              output_tokens: 10000,
              title: "Test session",
            },
          ],
          completed: [],
          total: 1,
          tool_distribution: { terminal: 20, read_file: 5 },
        },
        "/api/config/cron-jobs": { jobs: [], count: 0 },
        "/api/config/rl-runs": {
          configured: false,
          has_tinker_key: false,
          has_wandb_key: false,
          tinker_atropos_exists: true,
          runs: [],
          run_count: 0,
        },
      })
    );

    const queryClient = createTestQueryClient();
    render(<LoopsPage />, {
      wrapper: createQueryClientWrapper(queryClient),
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Test session").length).toBeGreaterThan(0);
    expect(screen.getAllByText("100 msgs").length).toBeGreaterThan(0);
    expect(screen.getAllByText("25 tools").length).toBeGreaterThan(0);
    expect(screen.getAllByText("terminal").length).toBeGreaterThan(0);
  });
});
