import { clamp, formatUsd } from "../../lib/utils";

export function BudgetBar({ spent, limit }: { spent: number; limit: number }) {
  const pct = limit > 0 ? clamp((spent / limit) * 100, 0, 100) : 0;
  const tone = pct >= 100 ? "is-red" : pct >= 80 ? "is-amber" : "is-emerald";

  return (
    <div className="budget-bar">
      <div className="budget-bar__meta">
        <span>{formatUsd(spent)} spent</span>
        <span>{limit > 0 ? `${pct.toFixed(0)}% of ${formatUsd(limit)}` : "No limit set"}</span>
      </div>
      <div className="budget-bar__track">
        <div className={`budget-bar__fill ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
