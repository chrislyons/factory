import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useMemo,
  useState
} from "react";
import { AGENTS, DOC_LINKS, NAV_LINKS } from "../lib/constants";

interface CommandItem {
  href: string;
  label: string;
  group: string;
}

interface ActiveLoopSearchResult {
  loop_id: string;
  spec?: {
    name?: string;
    agent_id?: string;
  };
}

interface CommandPaletteContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
}

const CommandPaletteContext = createContext<CommandPaletteContextValue | null>(null);

export function CommandPaletteProvider({ children }: PropsWithChildren) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dynamicItems, setDynamicItems] = useState<CommandItem[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    async function loadDynamicItems() {
      const nextItems: CommandItem[] = [];

      try {
        const taskResponse = await fetch("/jobs.json", { cache: "no-store" });
        if (taskResponse.ok) {
          const document = (await taskResponse.json()) as {
            tasks?: Array<{ id: string; title: string; assignee?: string | null }>;
          };
          for (const task of document.tasks ?? []) {
            nextItems.push({
              href: "/pages/jobs.html#task-list",
              label: `${task.title} (${task.id})`,
              group: "Tasks"
            });
          }
        }
      } catch {
        // Optional runtime data.
      }

      try {
        const approvalResponse = await fetch("/approvals/pending", { cache: "no-store" });
        if (approvalResponse.ok) {
          const approvals = (await approvalResponse.json()) as Array<{ id: string; agent_name: string; gate_type: string }>;
          for (const approval of approvals) {
            nextItems.push({
              href: "/pages/approvals.html",
              label: `${approval.agent_name} · ${approval.gate_type}`,
              group: "Approvals"
            });
          }
        }
      } catch {
        // Optional runtime data.
      }

      try {
        const loopResponse = await fetch("/loops", { cache: "no-store" });
        if (loopResponse.ok) {
          const loops = (await loopResponse.json()) as ActiveLoopSearchResult[];
          for (const loop of loops) {
            nextItems.push({
              href: `/pages/loops.html?loop=${loop.loop_id}`,
              label: `${loop.spec?.name ?? loop.loop_id} (${loop.spec?.agent_id ?? "unknown"})`,
              group: "Loops"
            });
          }
        }
      } catch {
        // Optional runtime data.
      }

      if (!cancelled) {
        setDynamicItems(nextItems);
        setActiveIndex(0);
      }
    }

    void loadDynamicItems();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const items = useMemo<CommandItem[]>(
    () => [
      ...NAV_LINKS.map((link) => ({ ...link, group: "Navigation" })),
      ...DOC_LINKS.map((link) => ({ ...link, group: "Docs" })),
      ...AGENTS.map((agent) => ({
        href: `/pages/agents/${agent.id}.html`,
        label: `${agent.label} agent detail`,
        group: "Agents"
      })),
      ...dynamicItems
    ],
    [dynamicItems]
  );

  const filtered = items.filter((item) =>
    `${item.group} ${item.label}`.toLowerCase().includes(query.trim().toLowerCase())
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((index) => (filtered.length === 0 ? 0 : (index + 1) % filtered.length));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((index) => (filtered.length === 0 ? 0 : (index - 1 + filtered.length) % filtered.length));
      }
      if (event.key === "Enter" && filtered[activeIndex]) {
        event.preventDefault();
        window.location.href = filtered[activeIndex].href;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeIndex, filtered, open]);

  return (
    <CommandPaletteContext.Provider value={{ open, setOpen }}>
      {children}
      {open ? (
        <div className="command-palette-backdrop" onClick={() => setOpen(false)}>
          <div className="command-palette" onClick={(event) => event.stopPropagation()}>
            <div className="command-palette__header">
              <input
                autoFocus
                className="command-palette__input"
                placeholder="Search pages, agents, docs..."
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="command-palette__results">
              {filtered.map((item) => (
                <a
                  key={`${item.group}-${item.href}`}
                  className={`command-palette__result ${filtered[activeIndex] === item ? "is-active" : ""}`}
                  href={item.href}
                  onClick={() => setOpen(false)}
                >
                  <span>{item.label}</span>
                  <span>{item.group}</span>
                </a>
              ))}
              {filtered.length === 0 ? (
                <div className="command-palette__empty">No results for “{query}”.</div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </CommandPaletteContext.Provider>
  );
}

export function CommandPaletteButton() {
  const context = useContext(CommandPaletteContext);
  if (!context) return null;
  return (
    <button className="command-trigger" type="button" onClick={() => context.setOpen(true)}>
      <span>Command Palette</span>
      <kbd>⌘K</kbd>
    </button>
  );
}
