import { useNow } from "../../hooks/useNow";

export function SyncClock({
  updatedAt,
  stale
}: {
  updatedAt?: number;
  stale?: boolean;
}) {
  const now = useNow(1_000);

  const clockText = new Date(now).toLocaleTimeString("en-GB", { hour12: false });

  const isFresh = updatedAt ? (now - updatedAt) < 10_000 : false;
  const isStale = stale || false;

  const className = [
    "sync-clock",
    isFresh && "is-fresh",
    isStale && "is-stale"
  ].filter(Boolean).join(" ");

  return <span className={className}>{clockText}</span>;
}
