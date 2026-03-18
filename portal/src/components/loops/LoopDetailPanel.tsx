import type { ActiveLoop } from "../../lib/types";
import {
  formatMetricValue,
  loopApprovalGateLabel,
  loopTypeLabel,
  relativeTimestamp,
  rollbackMethodLabel
} from "../../lib/utils";
import { LoopStatusPill } from "./LoopStatusPill";

export function LoopDetailPanel({
  loop,
  actionSlot,
  heading = "Loop Detail"
}: {
  loop: ActiveLoop;
  actionSlot?: React.ReactNode;
  heading?: string;
}) {
  return (
    <div className="loop-detail-panel">
      <div className="run-viewer__header">
        <div className="stack-tight">
          <div className="loop-row__title">
            <strong>{loop.spec.name}</strong>
            <LoopStatusPill status={loop.status} />
          </div>
          <div className="loop-row__meta">
            <span>{loop.loop_id}</span>
            <span>{loopTypeLabel(loop.spec.loop_type)}</span>
            <span>{loopApprovalGateLabel(loop.spec.approval_gate)}</span>
            <a href={`/pages/agents/${loop.spec.agent_id}.html?tab=loops&loop=${loop.loop_id}`}>
              {loop.spec.agent_id}
            </a>
          </div>
        </div>
        {actionSlot}
      </div>

      <div className="loop-detail-grid">
        <section className="loop-detail-card">
          <h3>{heading}</h3>
          <p className="placeholder-copy">{loop.spec.objective}</p>
          <div className="loop-meta-grid">
            <div className="loop-meta-pair">
              <span>Iteration</span>
              <strong>
                {loop.current_iteration} / {loop.spec.budget.max_iterations}
              </strong>
            </div>
            <div className="loop-meta-pair">
              <span>Best Metric</span>
              <strong>{formatMetricValue(loop.best_metric)}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Tokens Used</span>
              <strong>{loop.total_tokens_used.toLocaleString()}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Worker CWD</span>
              <strong>{loop.spec.worker_cwd ?? "Unset"}</strong>
            </div>
          </div>
        </section>

        <section className="loop-detail-card">
          <h3>Metric</h3>
          <div className="loop-meta-grid">
            <div className="loop-meta-pair">
              <span>Name</span>
              <strong>{loop.spec.metric.name}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Baseline</span>
              <strong>{formatMetricValue(loop.spec.metric.baseline)}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Direction</span>
              <strong>{loop.spec.metric.direction}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Machine Readable</span>
              <strong>{loop.spec.metric.machine_readable ? "Yes" : "No"}</strong>
            </div>
          </div>
          <p className="placeholder-copy">{loop.spec.metric.formula}</p>
        </section>

        <section className="loop-detail-card">
          <h3>Budget & Rollback</h3>
          <div className="loop-meta-grid">
            <div className="loop-meta-pair">
              <span>Per Iteration</span>
              <strong>{loop.spec.budget.per_iteration}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Approval Gate</span>
              <strong>{loopApprovalGateLabel(loop.spec.approval_gate)}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Rollback</span>
              <strong>{rollbackMethodLabel(loop.spec.rollback.method)}</strong>
            </div>
            <div className="loop-meta-pair">
              <span>Scope</span>
              <strong>{loop.spec.rollback.scope}</strong>
            </div>
          </div>
          <pre className="config-viewer">{loop.spec.rollback.command}</pre>
        </section>

        <section className="loop-detail-card">
          <h3>Frozen Harness</h3>
          {loop.spec.frozen_harness.length === 0 ? (
            <div className="placeholder-copy">No frozen harness paths reported.</div>
          ) : (
            <div className="loop-path-list">
              {loop.spec.frozen_harness.map((path) => (
                <code key={path} className="loop-path-pill is-frozen">
                  {path}
                </code>
              ))}
            </div>
          )}
        </section>

        <section className="loop-detail-card">
          <h3>Mutable Surface</h3>
          {loop.spec.mutable_surface.length === 0 ? (
            <div className="placeholder-copy">No mutable paths reported.</div>
          ) : (
            <div className="loop-path-list">
              {loop.spec.mutable_surface.map((path) => (
                <code key={path} className="loop-path-pill is-mutable">
                  {path}
                </code>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="loop-iteration-list">
        <div className="surface-card__header">
          <div>
            <h3>Iteration Timeline</h3>
            <p>Derived from the loop engine iteration history.</p>
          </div>
        </div>
        {loop.iterations.length === 0 ? (
          <div className="placeholder-copy">No completed iterations yet.</div>
        ) : (
          loop.iterations
            .slice()
            .reverse()
            .map((iteration) => (
              <div key={`${loop.loop_id}-${iteration.iteration}`} className="loop-iteration-row">
                <div className="loop-iteration-row__header">
                  <strong>Iteration {iteration.iteration}</strong>
                  <span>{iteration.kept ? "Kept" : "Discarded"}</span>
                </div>
                <div className="loop-row__meta">
                  <span>Metric {formatMetricValue(iteration.metric_value)}</span>
                  <span>Delta {formatMetricValue(iteration.delta)}</span>
                  <span>{iteration.tokens_used.toLocaleString()} tokens</span>
                  <span>{relativeTimestamp(iteration.ended_at)}</span>
                </div>
              </div>
            ))
        )}
      </div>
    </div>
  );
}
