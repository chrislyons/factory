import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TranscriptTail } from "./TranscriptTail";

describe("TranscriptTail", () => {
  it("keeps only the latest entries in the compact tail", () => {
    render(
      <TranscriptTail
        entries={Array.from({ length: 7 }, (_, index) => ({
          seq: index + 1,
          message: `line ${index + 1}`,
          event_type: "checkpoint"
        }))}
      />
    );

    expect(screen.queryByText("#1")).not.toBeInTheDocument();
    expect(screen.getByText("#3")).toBeInTheDocument();
    expect(screen.getByText("line 7")).toBeInTheDocument();
  });
});
