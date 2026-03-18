export function EmptyState({
  title,
  detail
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon">✓</div>
      <div className="empty-state__title">{title}</div>
      {detail ? <div className="empty-state__detail">{detail}</div> : null}
    </div>
  );
}
