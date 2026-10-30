import { useEffect, useState, type FormEvent } from "react";
import type { Board } from "../types";

const NEW_BOARD = "__new";

type BoardSwitcherProps = {
  boards: Board[];
  current: Board | null;
  onSwitch: (board: Board) => void;
  onCreate: (name: string, description: string) => Promise<void>;
  onSave: (board: Board, name: string, description: string) => Promise<void>;
  onDelete: (board: Board) => Promise<void>;
};

type DialogState = { kind: "new" } | { kind: "edit"; board: Board } | null;

export function BoardSwitcher({ boards, current, onSwitch, onCreate, onSave, onDelete }: BoardSwitcherProps) {
  const [dialog, setDialog] = useState<DialogState>(null);

  return (
    <div className="board-switcher">
      <label className="sr-only" htmlFor="board-select">
        Board
      </label>
      <select
        id="board-select"
        className="board-select"
        value={current ? String(current.id) : ""}
        onChange={(event) => {
          if (event.target.value === NEW_BOARD) {
            setDialog({ kind: "new" });
            return;
          }
          const next = boards.find((board) => String(board.id) === event.target.value);
          if (next) onSwitch(next);
        }}
      >
        {boards.map((board) => (
          <option key={board.id} value={board.id}>
            {board.name}
          </option>
        ))}
        <option value={NEW_BOARD}>+ New board…</option>
      </select>
      {current ? (
        <button
          type="button"
          className="nav-btn"
          aria-label={`Edit ${current.name}`}
          title={current.description ?? "No domain description"}
          onClick={() => setDialog({ kind: "edit", board: current })}
        >
          ⋯
        </button>
      ) : null}
      {dialog ? (
        <BoardDialog
          board={dialog.kind === "edit" ? dialog.board : null}
          canDelete={boards.length > 1}
          onClose={() => setDialog(null)}
          onSubmit={async (name, description) => {
            if (dialog.kind === "edit") await onSave(dialog.board, name, description);
            else await onCreate(name, description);
            setDialog(null);
          }}
          onDelete={async (board) => {
            await onDelete(board);
            setDialog(null);
          }}
        />
      ) : null}
    </div>
  );
}

type BoardDialogProps = {
  board: Board | null;
  canDelete: boolean;
  onClose: () => void;
  onSubmit: (name: string, description: string) => Promise<void>;
  onDelete: (board: Board) => Promise<void>;
};

function BoardDialog({ board, canDelete, onClose, onSubmit, onDelete }: BoardDialogProps) {
  const [name, setName] = useState(board?.name ?? "");
  const [description, setDescription] = useState(board?.description ?? "");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent): void {
    event.preventDefault();
    if (!name.trim()) {
      setError("Enter a name first");
      return;
    }
    void run(() => onSubmit(name.trim(), description));
  }

  return (
    <div className="research-modal-backdrop" onClick={onClose}>
      <form
        className="research-modal board-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="board-dialog-title"
        onClick={(event) => event.stopPropagation()}
        onSubmit={submit}
      >
        <h3 id="board-dialog-title">{board ? "Edit board" : "New board"}</h3>
        <label>
          Name
          <input
            autoFocus
            value={name}
            placeholder="Thesis"
            onChange={(event) => {
              setName(event.target.value);
              setError(null);
            }}
          />
        </label>
        <label>
          What is this Board about? <small>(optional)</small>
          <textarea
            rows={3}
            value={description}
            placeholder="My MSIT thesis on local RAG for study notes."
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {error ? (
          <p className="board-dialog-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="board-dialog-actions">
          <button type="button" className="nav-btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="nav-btn board-primary" disabled={busy}>
            {board ? "Save" : "Create board"}
          </button>
        </div>
        {board ? (
          <fieldset className="board-danger">
            <legend>Delete board</legend>
            {canDelete ? (
              <>
                <p>
                  This deletes {board.note_count} {board.note_count === 1 ? "note" : "notes"} and{" "}
                  {board.folder_count} Files {board.folder_count === 1 ? "folder" : "folders"}. Papers it
                  references stay in your Library. This can't be undone.
                </p>
                <label>
                  Type “{board.name}” to confirm
                  <input value={confirm} onChange={(event) => setConfirm(event.target.value)} />
                </label>
                <button
                  type="button"
                  className="nav-btn board-delete"
                  disabled={busy || confirm.trim() !== board.name}
                  onClick={() => void run(() => onDelete(board))}
                >
                  Delete board
                </button>
              </>
            ) : (
              <p>You can't delete your last Board.</p>
            )}
          </fieldset>
        ) : null}
      </form>
    </div>
  );
}
