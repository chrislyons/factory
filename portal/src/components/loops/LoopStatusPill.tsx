import type { LoopStatus } from "../../lib/types";
import { cn, loopStatusLabel, loopStatusTone } from "../../lib/utils";

export function LoopStatusPill({ status }: { status: LoopStatus | string }) {
  return <span className={cn("loop-status-pill", loopStatusTone(status))}>{loopStatusLabel(status)}</span>;
}
