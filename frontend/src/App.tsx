import { useEffect, useState } from "react";
import { fetchHealth, fetchLlmPing } from "./api";
import { BoardView } from "./components/BoardView";
import { ResearchView } from "./components/research/ResearchView";
import { StatusPills } from "./components/StatusPills";
import { ThemeToggle } from "./components/ThemeToggle";
import { useTheme } from "./hooks/useTheme";
import type { PillState } from "./types";

type Workspace = "board" | "research";

function readWorkspace(): Workspace {
  return new URLSearchParams(window.location.search).get("view") === "research" ? "research" : "board";
}

export default function App() {
  const { pref, resolved, cycle } = useTheme();
  const [backend, setBackend] = useState<PillState>("loading");
  const [model, setModel] = useState<PillState>("loading");
  const [modelName, setModelName] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>(readWorkspace);

  function switchWorkspace(next: Workspace): void {
    const url = new URL(window.location.href);
    if (next === "research") url.searchParams.set("view", "research");
    else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
    setWorkspace(next);
  }

  useEffect(() => {
    function stripHash(): void {
      if (!window.location.hash) {
        return;
      }
      const url = `${window.location.pathname}${window.location.search}`;
      window.history.replaceState(null, "", url);
    }
    stripHash();
    window.addEventListener("hashchange", stripHash);
    return () => window.removeEventListener("hashchange", stripHash);
  }, []);

  useEffect(() => {
    void fetchHealth()
      .then((data) => {
        setBackend(data.status === "ok" ? "ok" : "error");
      })
      .catch(() => {
        setBackend("error");
      });

    void fetchLlmPing()
      .then((data) => {
        setModel(data.reachable ? "ok" : "error");
        setModelName(data.model);
      })
      .catch(() => {
        setModel("error");
      });
  }, []);

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>Note Atlas</h1>
          <p className="lede">A spatial notebook that extracts and links in the background.</p>
        </div>
        <div className="topbar-tools">
          <div className="workspace-tabs" role="tablist" aria-label="Workspace">
            {(["board", "research"] as const).map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                className="nav-btn"
                aria-selected={workspace === name}
                onClick={() => switchWorkspace(name)}
              >
                {name === "board" ? "Board" : "Research"}
              </button>
            ))}
          </div>
          <ThemeToggle pref={pref} onCycle={cycle} />
          <StatusPills backend={backend} model={model} modelName={modelName} />
        </div>
      </header>
      {workspace === "research" ? <ResearchView /> : <BoardView colorMode={resolved} />}
    </div>
  );
}
