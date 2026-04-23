import { cn } from "../../lib/utils";

/**
 * Unified memory budget bar — used on both Stats and Config pages.
 *
 * Shows three segments (inference / system / free) with a swatch legend.
 * When free memory drops below thresholds, labels change colour and a
 * critical warning banner is shown.
 *
 * Optionally shows per-model allocation breakdown when `models` is provided.
 */

export interface MemoryBudgetData {
  total_gb: number;
  available_gb: number;
  used_by_inference_gb: number;
  headroom_gb?: number;
  models?: {
    agent: string;
    provider: string;
    port: number | null;
    model: string;
    loaded: boolean;
    est_gb: number;
  }[];
}

export function MemoryBar({
  budget,
  className,
  showModels = false,
}: {
  budget: MemoryBudgetData;
  className?: string;
  showModels?: boolean;
}) {
  const {
    total_gb: total,
    used_by_inference_gb: inference,
    available_gb: available,
    headroom_gb: headroom,
    models,
  } = budget;
  if (total <= 0) return null;

  const system = Math.max(0, total - inference - available);
  const infPct = (inference / total) * 100;
  const sysPct = (system / total) * 100;
  const freePct = (available / total) * 100;

  const crit = available < 1.0;
  const tight = available < 4.0 && !crit;

  const headroomCrit = headroom != null && headroom < 1.0;
  const headroomTight = headroom != null && headroom < 2.0 && !headroomCrit;

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
        {headroom != null && (
          <span
            className={cn(
              headroomCrit && "memory-bar__value--crit",
              headroomTight && "memory-bar__value--tight",
            )}
          >
            <i className="memory-bar__swatch memory-bar__swatch--headroom" />
            Headroom {headroom.toFixed(1)} GB
          </span>
        )}
      </div>

      {crit && (
        <div className="memory-bar__warn">
          Memory critical — restarts blocked unless forced
        </div>
      )}

      {showModels && models && models.length > 0 && (
        <div className="memory-bar__models">
          <div className="memory-bar__models-heading">Model Allocation</div>
          {models.map((m) => {
            const pct = total > 0 ? (m.est_gb / total) * 100 : 0;
            return (
              <div
                key={`${m.agent}-${m.model}`}
                className={cn("memory-bar__model-row", !m.loaded && "memory-bar__model-row--unloaded")}
              >
                <div className="memory-bar__model-info">
                  <span className="memory-bar__model-agent">{m.agent}</span>
                  <span className="memory-bar__model-name">{m.model}</span>
                  {m.provider === "cloud" && (
                    <span className="memory-bar__model-cloud">cloud</span>
                  )}
                </div>
                <div className="memory-bar__model-bar">
                  <div
                    className={cn(
                      "memory-bar__model-fill",
                      m.loaded ? "memory-bar__model-fill--loaded" : "memory-bar__model-fill--unloaded"
                    )}
                    style={{ width: `${Math.max(pct, 1)}%` }}
                  />
                </div>
                <span className="memory-bar__model-size">
                  {m.est_gb > 0 ? `${m.est_gb.toFixed(1)} GB` : "—"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
