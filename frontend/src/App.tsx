import { useEffect, useState } from "react";
import {
  createBoard,
  deleteBoard,
  fetchBoards,
  fetchHealth,
  fetchLlmPing,
  fetchNote,
  openBoard,
  patchBoard,
  setActiveBoard,
} from "./api";
import { BoardSwitcher } from "./components/BoardSwitcher";
import { BoardView } from "./components/BoardView";
import { ResearchView, type ResearchTarget } from "./components/research/ResearchView";
import { FilesView } from "./files/FilesView";
import { StatusPills } from "./components/StatusPills";
import { ThemeToggle } from "./components/ThemeToggle";
import { useTheme } from "./hooks/useTheme";
import type { Board, PillState } from "./types";

type Workspace = "board" | "research" | "files";

const WORKSPACE_LABELS: Record<Workspace, string> = { board: "Canvas", research: "Research", files: "Files" };

// ?board=<slug> names the Board; without it, open the one used last.
function pickBoard(boards: Board[]): Board | null {
  const slug = new URLSearchParams(window.location.search).get("board");
  const named = slug ? boards.find((board) => board.slug === slug) : undefined;
  if (named) return named;
  const opened = [...boards].sort((a, b) => (b.last_opened_at ?? "").localeCompare(a.last_opened_at ?? ""));
  return opened[0] ?? null;
}

function writeBoardSlug(board: Board): void {
  const url = new URL(window.location.href);
  url.searchParams.set("board", board.slug);
  window.history.replaceState(null, "", url);
}

function readWorkspace(): Workspace {
  const view = new URLSearchParams(window.location.search).get("view");
  return view === "research" || view === "files" ? view : "board";
}

export default function App() {
  const { pref, resolved, cycle } = useTheme();
  const [backend, setBackend] = useState<PillState>("loading");
  const [model, setModel] = useState<PillState>("loading");
  const [modelName, setModelName] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>(readWorkspace);
  // Cross-links between a sent Claim and its board note; read once when the workspace mounts.
  const [researchTarget, setResearchTarget] = useState<ResearchTarget | null>(null);
  const [boardFocus, setBoardFocus] = useState<number | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [currentBoard, setCurrentBoard] = useState<Board | null>(null);

  function showBoard(board: Board): void {
    setActiveBoard(board.id);
    writeBoardSlug(board);
    setCurrentBoard(board);
    setBoardFocus(null);
    void openBoard(board.id).catch(() => undefined);
  }

  async function reloadBoards(): Promise<Board[]> {
    const next = await fetchBoards();
    setBoards(next);
    return next;
  }

  async function addBoard(name: string, description: string): Promise<void> {
    const created = await createBoard({ name, description });
    await reloadBoards();
    showBoard(created);
    switchWorkspace("board");
  }

  async function saveBoard(board: Board, name: string, description: string): Promise<void> {
    const saved = await patchBoard(board.id, { name, description });
    await reloadBoards();
    if (currentBoard?.id === saved.id) showBoard(saved);
  }

  async function removeBoard(board: Board): Promise<void> {
    await deleteBoard(board.id);
    const remaining = await reloadBoards();
    if (currentBoard?.id === board.id && remaining[0]) showBoard(remaining[0]);
  }

  useEffect(() => {
    void fetchBoards()
      .then((loaded) => {
        setBoards(loaded);
        const first = pickBoard(loaded);
        if (first) showBoard(first);
      })
      .catch(() => setBackend("error"));
    // Runs once: showBoard only uses state setters.
  }, []);

  function switchWorkspace(next: Workspace): void {
    const url = new URL(window.location.href);
    if (next !== "board") url.searchParams.set("view", next);
    else url.searchParams.delete("view");
    window.history.replaceState(null, "", url);
    setWorkspace(next);
  }

  function openStudy(studyId: number, claimId: number | null): void {
    setResearchTarget({ studyId, claimId });
    switchWorkspace("research");
  }

  function openNote(noteId: number): void {
    // The note may be on another Board (a sent Claim can be moved); show that Board first.
    void fetchNote(noteId)
      .then((note) => {
        const home = boards.find((board) => board.id === note.board_id);
        if (home && home.id !== currentBoard?.id) showBoard(home);
      })
      .catch(() => undefined)
      .finally(() => {
        setBoardFocus(noteId);
        switchWorkspace("board");
      });
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
          {workspace !== "research" ? (
            <BoardSwitcher
              boards={boards}
              current={currentBoard}
              onSwitch={showBoard}
              onCreate={addBoard}
              onSave={saveBoard}
              onDelete={removeBoard}
            />
          ) : null}
          <div className="workspace-tabs" role="tablist" aria-label="Workspace">
            {(["board", "research", "files"] as const).map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                className="nav-btn"
                aria-selected={workspace === name}
                onClick={() => switchWorkspace(name)}
              >
                {WORKSPACE_LABELS[name]}
              </button>
            ))}
          </div>
          <ThemeToggle pref={pref} onCycle={cycle} />
          <StatusPills backend={backend} model={model} modelName={modelName} />
        </div>
      </header>
      {workspace === "files" ? (
        <FilesView />
      ) : workspace === "research" ? (
        <ResearchView colorMode={resolved} target={researchTarget} onOpenNote={openNote} />
      ) : currentBoard ? (
        <BoardView
          key={currentBoard.id}
          colorMode={resolved}
          focusNoteId={boardFocus}
          onOpenStudy={openStudy}
        />
      ) : null}
    </div>
  );
}
