export function EmptyState({
  title,
  detail,
  compact = false,
  className
}: {
  title: string;
  detail?: string;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={`${compact ? "empty-state is-compact" : "empty-state"}${className ? ` ${className}` : ""}`}>
      <div className="empty-state__icon" aria-hidden="true" />
      <div className="empty-state__title">{title}</div>
      {detail ? <div className="empty-state__detail">{detail}</div> : null}
    </div>
  );
}
