import { useRef, useEffect, useCallback } from "react";
import type { TaskRecord, TaskBlock } from "../lib/types";
import { cn } from "../lib/utils";

interface SidePanelProps {
  open: boolean;
  view: "deps" | "completions";
  onClose: () => void;
  tasks: TaskRecord[];
  blocks: Record<string, TaskBlock>;
}

export function SidePanel({ open, view, onClose, tasks, blocks }: SidePanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const touchStartX = useRef(0);

  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const diff = e.changedTouches[0].clientX - touchStartX.current;
    if (diff > 80) onClose();
  }, [onClose]);

  const blockedTasks = tasks.filter(t => t.blocked_by.length > 0);
  const completedTasks = tasks
    .filter(t => t.status === "done")
    .sort((a, b) => new Date(b.updated ?? "").getTime() - new Date(a.updated ?? "").getTime());

  const title = view === "deps" ? "Dependencies" : "Completions";
  const subtitle = view === "deps"
    ? "Blocked work and unresolved chains"
    : "Completed jobs, most recent first";

  const items = view === "deps" ? blockedTasks : completedTasks;

  return (
    <>
      <div
        className={cn("side-panel__backdrop", open && "is-visible")}
        onClick={onClose}
      />
      <div
        ref={panelRef}
        className={cn("side-panel", open && "is-open")}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className="side-panel__header">
          <div>
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </div>
          <button className="secondary-button" type="button" onClick={onClose}>&times;</button>
        </div>
        <div className="side-panel__body">
          {items.length === 0 ? (
            <div className="side-panel__empty">
              {view === "deps" ? "No active dependencies" : "No completed jobs yet"}
            </div>
          ) : (
            <div className="dependency-list">
              {items.map(task => (
                <div key={task.id} className="dependency-card">
                  <strong>{task.title}</strong>
                  {view === "deps" ? (
                    <span>Blocked by {task.blocked_by.join(", ")}</span>
                  ) : (
                    <span>{blocks[task.block]?.label ?? task.block}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
