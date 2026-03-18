import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentDetailPage } from "./AgentDetailPage";

vi.mock("../hooks/usePortalQueries", () => ({
  useAgentDetail: vi.fn(),
  useAgentAction: vi.fn(),
  useLoopDetail: vi.fn(),
  useLoops: vi.fn(),
  useRunCancel: vi.fn(),
  useRunEvents: vi.fn()
}));

import {
  useAgentAction,
  useAgentDetail,
  useLoopDetail,
  useLoops,
  useRunCancel,
  useRunEvents
} from "../hooks/usePortalQueries";

const mockedUseAgentDetail = vi.mocked(useAgentDetail);
const mockedUseAgentAction = vi.mocked(useAgentAction);
const mockedUseLoopDetail = vi.mocked(useLoopDetail);
const mockedUseLoops = vi.mocked(useLoops);
const mockedUseRunCancel = vi.mocked(useRunCancel);
const mockedUseRunEvents = vi.mocked(useRunEvents);

describe("AgentDetailPage", () => {
  beforeEach(() => {
    mockedUseAgentDetail.mockReturnValue({
      data: {
        agent: {
          agent_id: "boot",
          name: "Boot",
          status: "active",
          model: "gpt-5.4",
          trust_level: "high",
          context_mode: "full",
          budget: {
            agent_id: "boot",
            monthly_limit_usd: 100,
            spent_this_month_usd: 30,
            status: { kind: "normal" },
            incidents: []
          },
          config: { rooms: ["factory"] },
          current_run: null
        },
        runs: [
          {
            id: "run-1",
            status: "succeeded",
            started_at: "2026-03-17T11:00:00Z",
            task: "Task one",
            cost_cents: 25
          },
          {
            id: "run-2",
            status: "failed",
            started_at: "2026-03-17T12:00:00Z",
            task: "Task two",
            cost_cents: 40
          }
        ]
      },
      dataUpdatedAt: Date.now(),
      error: null
    } as never);

    mockedUseAgentAction.mockReturnValue({
      mutate: vi.fn(),
      isPending: false
    } as never);

    mockedUseRunCancel.mockReturnValue({
      mutate: vi.fn(),
      isPending: false
    } as never);

    mockedUseLoops.mockReturnValue({
      data: [
        {
          loop_id: "loop-1",
          spec: {
            loop_id: "loop-1",
            name: "Research Loop",
            objective: "Improve metric",
            loop_type: "researcher",
            agent_id: "boot",
            metric: {
              name: "signal_density",
              formula: "sources / note",
              baseline: 1.2,
              direction: "higher_is_better",
              machine_readable: true
            },
            frozen_harness: ["notes/"],
            mutable_surface: ["drafts/"],
            budget: {
              per_iteration: "50000 tokens",
              max_iterations: 8
            },
            rollback: {
              method: "git_reset",
              command: "git reset --hard HEAD~1",
              scope: "repo"
            },
            approval_gate: "none",
            worker_cwd: "/tmp/loop"
          },
          status: "running",
          current_iteration: 2,
          iteration_tokens_used: 1200,
          total_tokens_used: 3200,
          best_metric: 1.45,
          iterations: []
        }
      ],
      dataUpdatedAt: Date.now(),
      error: null
    } as never);

    mockedUseLoopDetail.mockReturnValue({
      data: undefined,
      dataUpdatedAt: 0,
      error: null
    } as never);

    mockedUseRunEvents.mockReturnValue({
      data: [
        {
          run_id: "run-2",
          seq: 1,
          event_type: "loop_start",
          stream: "stderr",
          level: "error",
          message: "run-2 selected from query string",
          timestamp: "2026-03-17T12:00:15Z"
        }
      ]
    } as never);
  });

  it("hydrates the selected run from the URL query string and renders loop event labels cleanly", () => {
    window.history.replaceState({}, "", "/pages/agents/boot.html?tab=runs&run=run-2");
    render(<AgentDetailPage agentId="boot" />);

    expect(screen.getByText("Run History")).toBeInTheDocument();
    expect(screen.getByText("run-2 selected from query string")).toBeInTheDocument();
    expect(screen.getAllByText("failed").length).toBeGreaterThan(0);
    expect(screen.getByText("Loop Start")).toBeInTheDocument();
  });

  it("hydrates the selected loop from the URL query string on the loops tab", () => {
    window.history.replaceState({}, "", "/pages/agents/boot.html?tab=loops&loop=loop-1");
    render(<AgentDetailPage agentId="boot" />);

    expect(screen.getByText("Agent Loops")).toBeInTheDocument();
    expect(screen.getAllByText("Research Loop").length).toBeGreaterThan(0);
    expect(screen.getByText("Improve metric")).toBeInTheDocument();
  });
});
