import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TopologyPage } from "./TopologyPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("TopologyPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows waiting topology nodes when status feeds are unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not found", { status: 404 }))
    );

    const queryClient = createTestQueryClient();
    render(<TopologyPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Open detail view")).toHaveLength(4);
    expect(screen.getAllByText("waiting")).toHaveLength(4);
  });

  it("renders live agent statuses inside the topology cards", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes("/status/boot.json")) {
          return jsonResponse({ status: "running", last_updated: "2026-03-17T12:00:00Z" });
        }
        if (url.includes("/status/ig88.json")) {
          return jsonResponse({ status: "paused", last_updated: "2026-03-17T12:00:00Z" });
        }
        return jsonResponse({ status: "idle", last_updated: "2026-03-17T12:00:00Z" });
      })
    );

    const queryClient = createTestQueryClient();
    render(<TopologyPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("paused")).toBeInTheDocument();
  });
});
