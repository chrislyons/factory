import { useState, useRef, useEffect } from "react";
import { ASSIGNEES } from "../lib/constants";
import { cn } from "../lib/utils";

interface AssignDropdownProps {
  value: string | null;
  onChange: (assignee: string) => void;
  className?: string;
}

export function AssignDropdown({ value, onChange, className }: AssignDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const selected = ASSIGNEES.find(a => a.id === value);

  return (
    <div className={cn("assign-dropdown", className)} ref={ref}>
      <button
        className="assign-dropdown__trigger"
        type="button"
        onClick={() => setOpen(!open)}
      >
        {selected ? (
          <>
            <span className="assign-dropdown__dot" style={{ background: selected.color }} />
            <span>{selected.label}</span>
          </>
        ) : (
          <span className="assign-dropdown__unassigned">Unassigned</span>
        )}
      </button>
      {open && (
        <div className="assign-dropdown__menu">
          <button
            className={cn("assign-dropdown__option", !value && "is-selected")}
            type="button"
            onClick={() => { onChange("unassigned"); setOpen(false); }}
          >
            Unassigned
          </button>
          {ASSIGNEES.map(a => (
            <button
              key={a.id}
              className={cn("assign-dropdown__option", value === a.id && "is-selected")}
              type="button"
              onClick={() => { onChange(a.id); setOpen(false); }}
            >
              <span className="assign-dropdown__dot" style={{ background: a.color }} />
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
