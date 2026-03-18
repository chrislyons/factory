import { useEffect, useRef } from "react";
import type { CurrentRunTailEntry } from "../../lib/types";

export function TranscriptTail({
  entries,
  limit = 5
}: {
  entries: CurrentRunTailEntry[];
  limit?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const visible = entries.slice(Math.max(0, entries.length - limit));

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [visible]);

  return (
    <div ref={containerRef} className="transcript-tail">
      {visible.length === 0 ? (
        <div className="transcript-tail__empty">Waiting for transcript…</div>
      ) : (
        visible.map((entry) => (
          <div key={`${entry.seq}-${entry.message}`} className="transcript-tail__line">
            <span className="transcript-tail__seq">#{entry.seq}</span>
            <span>{entry.message}</span>
          </div>
        ))
      )}
    </div>
  );
}
