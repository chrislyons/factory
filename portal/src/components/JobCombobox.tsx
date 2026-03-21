import { useState, useRef, useEffect, useCallback } from "react";
import type { TaskRecord, TaskBlock } from "../lib/types";
import { cn } from "../lib/utils";

interface JobComboboxProps {
  tasks: TaskRecord[];
  blocks: Record<string, TaskBlock>;
  onFilter: (query: string) => void;
  onCreate: (title: string) => void;
}

export function JobCombobox({ tasks, blocks, onFilter, onCreate }: JobComboboxProps) {
  const [value, setValue] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [focusedIdx, setFocusedIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const matches = value.trim()
    ? tasks.filter(t => {
        const hay = [t.id, t.title, t.description, t.assignee, t.status, blocks[t.block]?.label]
          .filter(Boolean).join(" ").toLowerCase();
        return hay.includes(value.toLowerCase());
      }).slice(0, 8)
    : [];

  const totalItems = matches.length + (value.trim() ? 1 : 0);

  useEffect(() => {
    if (!showDropdown) return;
    function handleClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setShowDropdown(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showDropdown]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setValue(v);
    onFilter(v);
    setShowDropdown(v.trim().length > 0);
    setFocusedIdx(-1);
  };

  const scrollToTask = useCallback((taskId: string) => {
    const el = document.getElementById(`task-${taskId}`);
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.classList.add("is-highlighted");
      setTimeout(() => el.classList.remove("is-highlighted"), 600);
    }
    setShowDropdown(false);
  }, []);

  const handleCreate = () => {
    if (value.trim()) {
      onCreate(value.trim());
      setValue("");
      onFilter("");
      setShowDropdown(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!showDropdown) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusedIdx(prev => Math.min(prev + 1, totalItems - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusedIdx(prev => Math.max(prev - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (focusedIdx >= 0 && focusedIdx < matches.length) {
        scrollToTask(matches[focusedIdx].id);
      } else if (focusedIdx === matches.length || matches.length === 0) {
        handleCreate();
      } else {
        handleCreate();
      }
    } else if (e.key === "Escape") {
      setShowDropdown(false);
      setFocusedIdx(-1);
    }
  };

  return (
    <div className="job-combobox" ref={wrapRef}>
      <input
        ref={inputRef}
        className="text-input job-combobox__input"
        value={value}
        onChange={handleChange}
        onFocus={() => { if (value.trim()) setShowDropdown(true); }}
        onKeyDown={handleKeyDown}
        placeholder="Search or add a job..."
        autoComplete="off"
      />
      {showDropdown && (
        <div className="job-combobox__results">
          {matches.map((task, i) => (
            <button
              key={task.id}
              className={cn("job-combobox__result", focusedIdx === i && "is-focused")}
              type="button"
              onClick={() => scrollToTask(task.id)}
              onMouseEnter={() => setFocusedIdx(i)}
            >
              <span className={`task-status-chip is-${task.status}`}>{task.status}</span>
              <span className="job-combobox__result-title">{task.title}</span>
              <span className="job-combobox__result-id">{task.id.replace("job.", "")}</span>
            </button>
          ))}
          {value.trim() && (
            <button
              className={cn("job-combobox__create", focusedIdx === matches.length && "is-focused")}
              type="button"
              onClick={handleCreate}
              onMouseEnter={() => setFocusedIdx(matches.length)}
            >
              Create: <strong>{value.trim()}</strong>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
