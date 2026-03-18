import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LastUpdatedChip } from "./LastUpdatedChip";

describe("LastUpdatedChip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-17T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a coordinator waiting state without data", () => {
    render(<LastUpdatedChip />);
    expect(screen.getByText("Awaiting sync")).toBeInTheDocument();
  });

  it("marks stale snapshots explicitly", () => {
    render(<LastUpdatedChip updatedAt={Date.parse("2026-03-17T11:59:00Z")} stale />);
    expect(screen.getByText(/Last updated/i)).toHaveClass("last-updated-chip", "is-stale");
  });
});
