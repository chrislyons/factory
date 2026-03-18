import { useNow } from "../../hooks/useNow";
import { timeAgo } from "../../lib/utils";

export function LastUpdatedChip({
  updatedAt,
  stale
}: {
  updatedAt?: number;
  stale?: boolean;
}) {
  useNow(1_000);
  if (!updatedAt) {
    return <span className="last-updated-chip">Awaiting sync</span>;
  }

  return (
    <span className={stale ? "last-updated-chip is-stale" : "last-updated-chip"}>
      Last updated {timeAgo(new Date(updatedAt).toISOString())}
    </span>
  );
}
