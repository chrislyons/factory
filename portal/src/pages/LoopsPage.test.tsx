import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoopsPage } from "./LoopsPage";
import { createQueryClientWrapper, createTestQueryClient } from "../test/queryClient";

describe("LoopsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a waiting state when /loops returns 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url.includes("/loops")) {
          return new Response("not found", { status: 404 });
        }
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );

    const queryClient = createTestQueryClient();
    render(<LoopsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getAllByText("Waiting for coordinator…").length).toBeGreaterThan(0);
  });

  it("shows a stable empty state when /loops returns an empty array", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }))
    );

    const queryClient = createTestQueryClient();
    render(<LoopsPage />, {
      wrapper: createQueryClientWrapper(queryClient)
    });

    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
    expect(screen.getByText("No loops yet")).toBeInTheDocument();
  });
});
