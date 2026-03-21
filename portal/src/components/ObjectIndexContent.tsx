import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { SurfaceCard } from "./AppShell";
import { OBJECT_INDEX } from "../lib/objectIndex";

type SortCol = "name" | "type" | "description" | null;
type SortDir = "asc" | "desc";

export function ObjectIndexContent() {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [copiedName, setCopiedName] = useState<string | null>(null);
  const [exported, setExported] = useState(false);
  const [sortCol, setSortCol] = useState<SortCol>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const searchRef = useRef<HTMLInputElement>(null);
  const sectionRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

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

  const sorted = useMemo(() => {
    if (!sortCol) return filtered;
    return filtered.map(section => {
      const items = [...section.items].sort((a, b) => {
        const av = a[sortCol].toLowerCase();
        const bv = b[sortCol].toLowerCase();
        const cmp = av < bv ? -1 : av > bv ? 1 : 0;
        return sortDir === "asc" ? cmp : -cmp;
      });
      return { ...section, items };
    });
  }, [filtered, sortCol, sortDir]);

  const totalMatches = filtered.reduce((sum, s) => sum + s.items.length, 0);
  const isSearching = query.trim().length > 0;

  const handleSort = useCallback((col: SortCol) => {
    if (sortCol === col) {
      if (sortDir === "asc") {
        setSortDir("desc");
      } else {
        setSortCol(null);
        setSortDir("asc");
      }
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  }, [sortCol, sortDir]);

  const copyName = useCallback(async (name: string) => {
    await navigator.clipboard.writeText(name);
    setCopiedName(name);
    setTimeout(() => setCopiedName(null), 400);
  }, []);

  const exportMarkdown = useCallback(async () => {
    const lines: string[] = [];
    for (const section of sorted) {
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
  }, [sorted]);

  const setAllSections = useCallback((collapsed: boolean) => {
    const next: Record<string, boolean> = {};
    for (const s of OBJECT_INDEX) next[s.id] = !collapsed;
    setExpanded(next);
  }, []);

  const getVisibleSectionIds = useCallback(() => {
    return sorted.map(s => s.id);
  }, [sorted]);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const inSearch = document.activeElement === searchRef.current;

      if ((e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey && e.key.toLowerCase() === "e") {
        e.preventDefault();
        void exportMarkdown();
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        setAllSections(true);
        if (inSearch) {
          setQuery("");
          searchRef.current?.blur();
        }
        return;
      }

      if (e.key === "Tab" && searchRef.current) {
        e.preventDefault();
        if (inSearch) {
          searchRef.current.blur();
        } else {
          searchRef.current.focus();
          searchRef.current.select();
        }
        return;
      }

      if (inSearch) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          const ids = getVisibleSectionIds();
          if (ids.length) sectionRefs.current.get(ids[0])?.focus();
        }
        return;
      }

      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (!e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setAllSections(false);
        return;
      }

      if (e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
        return;
      }

      const ids = getVisibleSectionIds();
      const focused = document.activeElement;
      const currentId = ids.find(id => sectionRefs.current.get(id) === focused);
      const idx = currentId ? ids.indexOf(currentId) : -1;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          if (ids.length) {
            const next = idx < 0 ? 0 : Math.min(idx + 1, ids.length - 1);
            sectionRefs.current.get(ids[next])?.focus();
          }
          break;
        case "ArrowUp":
          e.preventDefault();
          if (idx <= 0) {
            searchRef.current?.focus();
            searchRef.current?.select();
          } else {
            sectionRefs.current.get(ids[idx - 1])?.focus();
          }
          break;
        case "ArrowRight":
          if (currentId) {
            e.preventDefault();
            setExpanded(prev => ({ ...prev, [currentId]: true }));
          }
          break;
        case "ArrowLeft":
          if (currentId) {
            e.preventDefault();
            setExpanded(prev => ({ ...prev, [currentId]: false }));
          }
          break;
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [sorted, setAllSections, getVisibleSectionIds, exportMarkdown]);

  function toggleSection(id: string) {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }));
  }

  function isSectionExpanded(id: string) {
    if (isSearching) return true;
    return expanded[id] ?? false;
  }

  function sortGlyph(col: SortCol) {
    if (sortCol !== col) return null;
    return <span className="obj-sort-indicator">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>;
  }

  return (
    <>
      <button
        className={`obj-export-btn${exported ? " is-exported" : ""}`}
        type="button"
        onClick={() => void exportMarkdown()}
        style={{ marginBottom: 12 }}
      >
        {exported ? "Copied!" : "Export to Markdown"}
      </button>

      <div className="obj-search-wrap">
        <span className="obj-search-icon">&#x2315;</span>
        <input
          ref={searchRef}
          className="obj-search-input"
          type="text"
          placeholder="Search objects..."
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
            &times;
          </button>
        )}
      </div>

      {sorted.map(section => {
        const open = isSectionExpanded(section.id);
        return (
          <div key={section.id} className="obj-section-card">
            <button
              ref={el => { if (el) sectionRefs.current.set(section.id, el); }}
              className={`obj-section-header${open ? "" : " is-collapsed"}`}
              type="button"
              onClick={() => toggleSection(section.id)}
            >
              <span className="obj-section-arrow">{"\u25BC"}</span>
              <span className="obj-section-title">{section.title}</span>
              <span className="obj-section-count">{isSearching ? section.items.length : section.count}</span>
            </button>
            {open && (
              <div className="obj-section-body">
                <table className="obj-table">
                  <thead>
                    <tr>
                      <th onClick={() => handleSort("name")} style={{ cursor: "pointer" }}>
                        Name{sortGlyph("name")}
                      </th>
                      <th onClick={() => handleSort("type")} style={{ cursor: "pointer" }}>
                        Type{sortGlyph("type")}
                      </th>
                      <th onClick={() => handleSort("description")} style={{ cursor: "pointer" }}>
                        Description{sortGlyph("description")}
                      </th>
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

      {sorted.length === 0 && isSearching && (
        <SurfaceCard title="No Results">
          <p className="placeholder-copy">No objects match &ldquo;{query}&rdquo;</p>
        </SurfaceCard>
      )}
    </>
  );
}
