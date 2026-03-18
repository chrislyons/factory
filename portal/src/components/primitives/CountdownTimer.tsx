import { useNow } from "../../hooks/useNow";
import { cn } from "../../lib/utils";

function formatRemaining(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function CountdownTimer({
  requestedAt,
  timeoutMs
}: {
  requestedAt: string;
  timeoutMs: number;
}) {
  const now = useNow();
  const start = new Date(requestedAt).getTime();
  const deadline = start + timeoutMs;
  const remaining = deadline - now;
  const pct = timeoutMs > 0 ? remaining / timeoutMs : 0;

  return (
    <span className={cn("countdown", pct <= 0.2 && "is-urgent", remaining <= 0 && "is-expired")}>
      {remaining <= 0 ? "Timed out" : formatRemaining(remaining)}
    </span>
  );
}
