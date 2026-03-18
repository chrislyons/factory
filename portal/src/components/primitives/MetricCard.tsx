import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  href,
  detail,
  danger
}: {
  label: string;
  value: ReactNode;
  href?: string;
  detail?: ReactNode;
  danger?: boolean;
}) {
  const content = (
    <>
      <span className="metric-card__label">{label}</span>
      <span className={danger ? "metric-card__value is-danger" : "metric-card__value"}>{value}</span>
      {detail ? <span className="metric-card__detail">{detail}</span> : null}
    </>
  );

  return href ? (
    <a className="metric-card" href={href}>
      {content}
    </a>
  ) : (
    <div className="metric-card">{content}</div>
  );
}
