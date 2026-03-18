import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BudgetBar } from "./BudgetBar";

describe("BudgetBar", () => {
  it("uses the emerald tone below the warning threshold", () => {
    const { container } = render(<BudgetBar spent={79} limit={100} />);

    expect(screen.getByText("$79.00 spent")).toBeInTheDocument();
    expect(container.querySelector(".budget-bar__fill")).toHaveClass("is-emerald");
  });

  it("uses the red tone and clamps width once exhausted", () => {
    const { container } = render(<BudgetBar spent={125} limit={100} />);

    expect(screen.getByText("100% of $100")).toBeInTheDocument();
    expect(container.querySelector(".budget-bar__fill")).toHaveClass("is-red");
    expect(container.querySelector(".budget-bar__fill")).toHaveStyle({ width: "100%" });
  });
});
