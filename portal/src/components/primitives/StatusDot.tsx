import { cn } from "../../lib/utils";

export function StatusDot({ status }: { status: "active" | "idle" | "paused" | "error" }) {
  return (
    <span className={cn("status-dot-ui", `is-${status}`)}>
      <span className="status-dot-ui__core" />
    </span>
  );
}
