type AppView = "capture" | "repository" | "map" | "ask" | "board";

type ViewNavProps = {
  view: AppView;
  onChange: (view: AppView) => void;
};

export function ViewNav({ view, onChange }: ViewNavProps) {
  return (
    <nav className="view-nav" aria-label="App views">
      <button
        type="button"
        className={view === "capture" ? "nav-btn active" : "nav-btn"}
        onClick={() => onChange("capture")}
      >
        Capture
      </button>
      <button
        type="button"
        className={view === "repository" ? "nav-btn active" : "nav-btn"}
        onClick={() => onChange("repository")}
      >
        Repository
      </button>
      <button
        type="button"
        className={view === "map" ? "nav-btn active" : "nav-btn"}
        onClick={() => onChange("map")}
      >
        Map
      </button>
      <button
        type="button"
        className={view === "ask" ? "nav-btn active" : "nav-btn"}
        onClick={() => onChange("ask")}
      >
        Ask
      </button>
      <button
        type="button"
        className={view === "board" ? "nav-btn active" : "nav-btn"}
        onClick={() => onChange("board")}
      >
        Board
      </button>
    </nav>
  );
}

export type { AppView };
