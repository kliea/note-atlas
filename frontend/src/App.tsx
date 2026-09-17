import { useEffect, useState } from "react";
import { fetchHealth, fetchLlmPing } from "./api";
import { BoardView } from "./components/BoardView";
import { StatusPills } from "./components/StatusPills";
import { ThemeToggle } from "./components/ThemeToggle";
import { useTheme } from "./hooks/useTheme";
import type { PillState } from "./types";

export default function App() {
  const { pref, resolved, cycle } = useTheme();
  const [backend, setBackend] = useState<PillState>("loading");
  const [model, setModel] = useState<PillState>("loading");
  const [modelName, setModelName] = useState<string | null>(null);

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
          <ThemeToggle pref={pref} onCycle={cycle} />
          <StatusPills backend={backend} model={model} modelName={modelName} />
        </div>
      </header>
      <BoardView colorMode={resolved} />
    </div>
  );
}
