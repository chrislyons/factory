import { useState, useEffect, useRef, useCallback, useMemo } from "react";

interface RepoEntry {
  name: string;
  gallery?: string;
  gallery_title?: string;
  gallery_mtime?: string;
  commands?: string;
  commands_title?: string;
  commands_mtime?: string;
}

interface IndexData {
  repos: RepoEntry[];
  generated_at?: string;
}

const GalleryIcon = () => (
  <svg className="docs-repo-link__icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <rect x="1.5" y="3.5" width="13" height="10" rx="1.5" />
    <polyline points="1.5,10 5,6.5 8,9.5 11,7 14.5,10" />
    <circle cx="5" cy="5.5" r="0.8" fill="currentColor" stroke="none" />
  </svg>
);

const CommandsIcon = () => (
  <svg className="docs-repo-link__icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3,5 6,8 3,11" />
    <line x1="8" y1="11" x2="13" y2="11" />
  </svg>
);


function galleryHref(repoName: string): string {
  return `/galleries/${repoName}_architecture-gallery.html`;
}

function commandsHref(repoName: string): string {
  return `/commands/${repoName}_repo-commands.html`;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

function latestMtime(repo: RepoEntry): string | undefined {
  const times = [repo.gallery_mtime, repo.commands_mtime].filter(Boolean) as string[];
  if (!times.length) return undefined;
  return times.sort().pop();
}

export function RepoExplorer() {
  const [allRepos, setAllRepos] = useState<RepoEntry[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const [focusedCell, setFocusedCell] = useState<"gallery" | "commands">("gallery");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | undefined>();
  const searchRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<Map<number, HTMLTableRowElement>>(new Map());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/index.json");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: IndexData = await res.json();
      const withDocs = data.repos.filter(r => r.gallery || r.commands);
      setAllRepos(withDocs);
      setGeneratedAt(data.generated_at);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load index");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return allRepos;
    const q = searchQuery.toLowerCase();
    return allRepos.filter(r =>
      r.name.toLowerCase().includes(q) ||
      r.gallery_title?.toLowerCase().includes(q) ||
      r.commands_title?.toLowerCase().includes(q)
    );
  }, [allRepos, searchQuery]);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const inSearch = document.activeElement === searchRef.current;
      const tag = (e.target as HTMLElement)?.tagName;

      if (e.key === "Escape") {
        e.preventDefault();
        setSearchQuery("");
        setFocusedIndex(-1);
        searchRef.current?.blur();
        return;
      }

      if (e.key === "/" && !inSearch && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        searchRef.current?.focus();
        return;
      }

      if (inSearch && e.key === "ArrowDown") {
        e.preventDefault();
        setFocusedIndex(0);
        setFocusedCell("gallery");
        searchRef.current?.blur();
        return;
      }

      if (inSearch) return;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setFocusedIndex(prev => Math.min(prev + 1, filtered.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          if (focusedIndex <= 0) {
            setFocusedIndex(-1);
            searchRef.current?.focus();
          } else {
            setFocusedIndex(prev => prev - 1);
          }
          break;
        case "ArrowLeft":
          e.preventDefault();
          setFocusedCell("gallery");
          break;
        case "ArrowRight":
          e.preventDefault();
          setFocusedCell("commands");
          break;
        case "Enter":
        case " ": {
          if (focusedIndex >= 0 && focusedIndex < filtered.length) {
            e.preventDefault();
            const repo = filtered[focusedIndex];
            if (focusedCell === "gallery" && repo.gallery) {
              window.open(galleryHref(repo.name), "_blank");
            } else if (focusedCell === "commands" && repo.commands) {
              window.open(commandsHref(repo.name), "_blank");
            }
          }
          break;
        }
        case "g": {
          if (!e.metaKey && !e.ctrlKey && focusedIndex >= 0) {
            const repo = filtered[focusedIndex];
            if (repo.gallery) window.open(galleryHref(repo.name), "_blank");
          }
          break;
        }
        case "c": {
          if (!e.metaKey && !e.ctrlKey && focusedIndex >= 0) {
            const repo = filtered[focusedIndex];
            if (repo.commands) window.open(commandsHref(repo.name), "_blank");
          }
          break;
        }
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [filtered, focusedIndex, focusedCell]);

  useEffect(() => {
    if (focusedIndex >= 0) {
      rowRefs.current.get(focusedIndex)?.scrollIntoView({ block: "nearest" });
    }
  }, [focusedIndex]);

  if (loading) {
    return (
      <div className="docs-grid-wrap">
        <table className="docs-repo-grid">
          <thead>
            <tr>
              <th>#</th>
              <th>Repository</th>
              <th>Gallery</th>
              <th>Commands</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 12 }, (_, i) => (
              <tr key={i} className="docs-repo-row">
                <td><span className="docs-skeleton" style={{ width: 16 }} /></td>
                <td><span className="docs-skeleton" style={{ width: 100 + Math.random() * 60 }} /></td>
                <td><span className="docs-skeleton" style={{ width: 50 }} /></td>
                <td><span className="docs-skeleton" style={{ width: 50 }} /></td>
                <td><span className="docs-skeleton" style={{ width: 40 }} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (error) {
    return (
      <div className="docs-state-card">
        <div className="docs-state-card__icon">
          <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="16" cy="16" r="13" />
            <line x1="16" y1="10" x2="16" y2="18" />
            <circle cx="16" cy="22" r="1" fill="currentColor" stroke="none" />
          </svg>
        </div>
        <h3>Failed to load index</h3>
        <p>{error}</p>
        <button className="docs-retry-btn" type="button" onClick={() => void fetchData()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="docs-meta-row">
        {generatedAt && (
          <span className="docs-meta-chip">
            <span className="docs-meta-chip__label">Updated</span>
            <span className="docs-meta-chip__value">{relativeTime(generatedAt)}</span>
          </span>
        )}
        <span className="docs-meta-chip">
          <span className="docs-meta-chip__label">Source</span>
          <span className="docs-meta-chip__value">codex-commandsheets</span>
        </span>
        <span className="docs-meta-chip">
          <span className="docs-meta-chip__label">Repos</span>
          <span className="docs-meta-chip__value">{filtered.length}</span>
        </span>
      </div>

      <div className="docs-search-wrap">
        <span className="docs-search-icon">&#x2315;</span>
        <input
          ref={searchRef}
          className="docs-search-input"
          type="text"
          placeholder="Search repositories..."
          value={searchQuery}
          onChange={e => { setSearchQuery(e.target.value); setFocusedIndex(-1); }}
          autoComplete="off"
          spellCheck={false}
        />
        {searchQuery && (
          <span className="docs-search-count">{filtered.length}</span>
        )}
        <button
          className={`docs-search-clear${searchQuery ? " visible" : ""}`}
          type="button"
          onClick={() => setSearchQuery("")}
        >
          &times;
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="docs-state-card">
          <h3>No matches</h3>
          <p>No repositories match &ldquo;{searchQuery}&rdquo;</p>
        </div>
      ) : (
        <div className="docs-grid-wrap">
          <table className="docs-repo-grid">
            <thead>
              <tr>
                <th>#</th>
                <th>Repository</th>
                <th>Gallery</th>
                <th>Commands</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((repo, i) => {
                const mtime = latestMtime(repo);
                return (
                  <tr
                    key={repo.name}
                    ref={el => { if (el) rowRefs.current.set(i, el); }}
                    className={`docs-repo-row${focusedIndex === i ? " is-row-focused" : ""}`}
                  >
                    <td>{i + 1}</td>
                    <td><span className="docs-repo-name">{repo.name}</span></td>
                    <td>
                      {repo.gallery ? (
                        <a
                          className={`docs-repo-link docs-cell-link${focusedIndex === i && focusedCell === "gallery" ? " is-cell-focused" : ""}`}
                          href={galleryHref(repo.name)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <GalleryIcon />
                          <span className="docs-repo-link__label">Gallery</span>
                        </a>
                      ) : (
                        <span className="docs-cell-muted">&mdash;</span>
                      )}
                    </td>
                    <td>
                      {repo.commands ? (
                        <a
                          className={`docs-repo-link docs-cell-link${focusedIndex === i && focusedCell === "commands" ? " is-cell-focused" : ""}`}
                          href={commandsHref(repo.name)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <CommandsIcon />
                          <span className="docs-repo-link__label">Commands</span>
                        </a>
                      ) : (
                        <span className="docs-cell-muted">&mdash;</span>
                      )}
                    </td>
                    <td className="docs-cell-muted">
                      {mtime ? relativeTime(mtime) : "\u2014"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
