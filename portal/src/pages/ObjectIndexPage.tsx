import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { OBJECT_INDEX } from "../lib/objectIndex";

export function ObjectIndexPage() {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [copiedName, setCopiedName] = useState<string | null>(null);
  const [exported, setExported] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    if (!query.trim()) return OBJECT_INDEX;
    const q = query.toLowerCase();
    return OBJECT_INDEX.map(section => ({
      ...section,
      items: section.items.filter(item =>
        item.name.toLowerCase().includes(q) ||
        item.type.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q)
      )
    })).filter(section => section.items.length > 0);
  }, [query]);

  const totalMatches = filtered.reduce((sum, s) => sum + s.items.length, 0);
  const isSearching = query.trim().length > 0;

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") {
          setQuery("");
          searchRef.current?.blur();
        }
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  const copyName = useCallback(async (name: string) => {
    await navigator.clipboard.writeText(name);
    setCopiedName(name);
    setTimeout(() => setCopiedName(null), 400);
  }, []);

  const exportMarkdown = useCallback(async () => {
    const lines: string[] = [];
    for (const section of filtered) {
      lines.push(`## ${section.title}\n`);
      lines.push("| Name | Type | Description |");
      lines.push("|------|------|-------------|");
      for (const item of section.items) {
        lines.push(`| \`${item.name}\` | ${item.type} | ${item.description} |`);
      }
      lines.push("");
    }
    await navigator.clipboard.writeText(lines.join("\n"));
    setExported(true);
    setTimeout(() => setExported(false), 1200);
  }, [filtered]);

  function toggleSection(id: string) {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }));
  }

  function isSectionExpanded(id: string) {
    if (isSearching) return true;
    return expanded[id] ?? false;
  }

  return (
    <AppShell title="Object Index" pageKey="/pages/object-index.html">
      <div className="obj-hero-row">
        <p className="obj-hero-desc">
          All CSS classes, components, hooks, types, constants, API functions and design tokens. Click any name to copy.
        </p>
        <button
          className={`obj-export-btn${exported ? " is-exported" : ""}`}
          type="button"
          onClick={() => void exportMarkdown()}
        >
          {exported ? "Copied!" : "Export to Markdown"}
        </button>
      </div>

      <div className="obj-search-wrap">
        <span className="obj-search-icon">&#x2315;</span>
        <input
          ref={searchRef}
          className="obj-search-input"
          type="text"
          placeholder="Search objects…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        {isSearching && (
          <span className="obj-search-count">{totalMatches}</span>
        )}
        {isSearching && (
          <button
            className="obj-search-clear"
            type="button"
            onClick={() => setQuery("")}
          >
            ×
          </button>
        )}
      </div>

      <div className="obj-kbd-hints">
        <kbd>/</kbd> search
        <kbd>Esc</kbd> clear
      </div>

      {filtered.map(section => {
        const open = isSectionExpanded(section.id);
        return (
          <div key={section.id} className="obj-section-card">
            <button
              className={`obj-section-header${open ? "" : " is-collapsed"}`}
              type="button"
              onClick={() => toggleSection(section.id)}
            >
              <span className="obj-section-arrow">▼</span>
              <span className="obj-section-title">{section.title}</span>
              <span className="obj-section-count">{isSearching ? section.items.length : section.count}</span>
            </button>
            {open && (
              <div className="obj-section-body">
                <table className="obj-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {section.items.map(item => (
                      <tr key={item.name}>
                        <td>
                          <code
                            className={`obj-name${copiedName === item.name ? " is-copied" : ""}`}
                            onClick={() => void copyName(item.name)}
                          >
                            {item.name}
                          </code>
                        </td>
                        <td><span className="obj-type-badge">{item.type}</span></td>
                        <td className="obj-desc">{item.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}

      {filtered.length === 0 && isSearching && (
        <SurfaceCard title="No Results">
          <p className="placeholder-copy">No objects match &ldquo;{query}&rdquo;</p>
        </SurfaceCard>
      )}
    </AppShell>
  );
}
