import { useState, useCallback } from "react";
import { AppShell } from "../components/AppShell";
import { SyncClock } from "../components/primitives/SyncClock";
import { RepoExplorer } from "../components/RepoExplorer";
import { ObjectIndexContent } from "../components/ObjectIndexContent";

function getInitialTab(): "repos" | "objects" {
  const params = new URLSearchParams(window.location.search);
  return params.get("tab") === "objects" ? "objects" : "repos";
}

export function DocsPage() {
  const [tab, setTabState] = useState<"repos" | "objects">(getInitialTab);

  const setTab = useCallback((next: "repos" | "objects") => {
    setTabState(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url.toString());
  }, []);

  return (
    <AppShell
      title="Documentation"
      pageKey="/pages/docs.html"
      statusSlot={<SyncClock updatedAt={Date.now()} />}
    >
      <div className="docs-tabs">
        <button
          className={`docs-tab${tab === "repos" ? " is-active" : ""}`}
          type="button"
          onClick={() => setTab("repos")}
        >
          Reference Docs
        </button>
        <button
          className={`docs-tab${tab === "objects" ? " is-active" : ""}`}
          type="button"
          onClick={() => setTab("objects")}
        >
          Object Index
        </button>
      </div>

      {tab === "repos" ? <RepoExplorer /> : <ObjectIndexContent />}
    </AppShell>
  );
}
