import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CountdownTimer } from "./CountdownTimer";

describe("CountdownTimer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-17T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a live urgent countdown near expiry", () => {
    render(
      <CountdownTimer
        requestedAt="2026-03-17T11:59:12Z"
        timeoutMs={60_000}
      />
    );

    expect(screen.getByText("12s")).toHaveClass("countdown", "is-urgent");
  });

  it("shows timed out when the deadline has passed", () => {
    render(
      <CountdownTimer
        requestedAt="2026-03-17T11:58:00Z"
        timeoutMs={60_000}
      />
    );

    expect(screen.getByText("Timed out")).toHaveClass("is-expired");
  });
});
