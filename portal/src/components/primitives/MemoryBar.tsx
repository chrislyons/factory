import { cn } from "../../lib/utils";

/**
 * Unified memory budget bar — used on both Stats and Config pages.
 *
 * Shows three segments (inference / system / free) with a swatch legend.
 * When free memory drops below thresholds, labels change colour and a
 * critical warning banner is shown.
 */

export interface MemoryBudgetData {
  total_gb: number;
  available_gb: number;
  used_by_inference_gb: number;
}

export function MemoryBar({
  budget,
  className,
}: {
  budget: MemoryBudgetData;
  className?: string;
}) {
  const { total_gb: total, used_by_inference_gb: inference, available_gb: available } = budget;
  if (total <= 0) return null;

  const system = Math.max(0, total - inference - available);
  const infPct = (inference / total) * 100;
  const sysPct = (system / total) * 100;
  const freePct = (available / total) * 100;

  const crit = available < 1.0;
  const tight = available < 4.0 && !crit;

  return (
    <div className={cn("memory-bar", className)}>
      <div className="memory-bar__track">
        {inference > 0 && (
          <div
            className={cn("memory-bar__seg memory-bar__seg--inference", crit && "memory-bar__seg--crit")}
            style={{ width: `${infPct}%` }}
            title={`Inference: ${inference.toFixed(1)} GB`}
          />
        )}
        {system > 0 && (
          <div
            className="memory-bar__seg memory-bar__seg--system"
            style={{ width: `${sysPct}%` }}
            title={`System: ${system.toFixed(1)} GB`}
          />
        )}
        <div
          className="memory-bar__seg memory-bar__seg--free"
          style={{ width: `${freePct}%` }}
          title={`Free: ${available.toFixed(1)} GB`}
        />
      </div>

      <div className="memory-bar__legend">
        <span>
          <i className="memory-bar__swatch memory-bar__swatch--inference" />
          Inference {inference.toFixed(1)} GB
        </span>
        <span>
          <i className="memory-bar__swatch memory-bar__swatch--system" />
          System {system.toFixed(1)} GB
        </span>
        <span
          className={cn(
            crit && "memory-bar__value--crit",
            tight && "memory-bar__value--tight",
          )}
        >
          <i
            className={cn(
              "memory-bar__swatch memory-bar__swatch--free",
              crit && "memory-bar__swatch--crit",
            )}
          />
          Free {available.toFixed(1)} GB / {total.toFixed(0)} GB
        </span>
      </div>

      {crit && (
        <div className="memory-bar__warn">
          Memory critical — restarts blocked unless forced
        </div>
      )}
    </div>
  );
}
