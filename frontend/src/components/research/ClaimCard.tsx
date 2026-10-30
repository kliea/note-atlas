import { useEffect, useRef, useState } from "react";
import type { Board, Claim } from "../../types";

type ClaimCardProps = {
  claim: Claim;
  onEdit: (id: number, text: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onKeep: (id: number) => Promise<void>;
  onSend: (id: number, boardId: number) => Promise<void>;
  onMove: (noteId: number, boardId: number) => Promise<void>;
  boards: Board[];
  onOpenNote: (noteId: number) => void;
  highlighted: boolean;
};

// Before sending: the Board it will go to (last opened first). After: where it is now.
function defaultBoardId(boards: Board[]): number | null {
  const opened = [...boards].sort((a, b) => (b.last_opened_at ?? "").localeCompare(a.last_opened_at ?? ""));
  return opened[0]?.id ?? null;
}

export function ClaimCard({
  claim,
  onEdit,
  onDelete,
  onKeep,
  onSend,
  onMove,
  boards,
  onOpenNote,
  highlighted,
}: ClaimCardProps) {
  const [target, setTarget] = useState<number | null>(null);
  const chosenBoard = claim.sent_board_id ?? target ?? defaultBoardId(boards);
  const cardRef = useRef<HTMLLIElement>(null);
  const [sending, setSending] = useState(false);
  const [showQuote, setShowQuote] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(claim.text);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saving, setSaving] = useState(false);

  async function save(): Promise<void> {
    const text = draft.trim();
    if (!text || text === claim.text) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onEdit(claim.id, text);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    if (highlighted) cardRef.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);

  async function send(): Promise<void> {
    if (chosenBoard === null) return;
    setSending(true);
    try {
      await onSend(claim.id, chosenBoard);
    } finally {
      setSending(false);
    }
  }

  async function chooseBoard(boardId: number): Promise<void> {
    if (claim.sent_note_id === null) {
      setTarget(boardId);
      return;
    }
    if (boardId === claim.sent_board_id) return;
    setSending(true);
    try {
      await onMove(claim.sent_note_id, boardId);
    } finally {
      setSending(false);
    }
  }

  const boardPicker =
    boards.length > 1 && chosenBoard !== null ? (
      <select
        className="research-board-select"
        aria-label={claim.sent_note_id === null ? "Board to send to" : "Move to another Board"}
        title={claim.sent_note_id === null ? "Board to send to" : "Move this note to another Board"}
        value={chosenBoard}
        disabled={sending}
        onChange={(event) => void chooseBoard(Number(event.target.value))}
      >
        {boards.map((board) => (
          <option key={board.id} value={board.id}>
            {board.name}
          </option>
        ))}
      </select>
    ) : null;

  return (
    <li
      ref={cardRef}
      className={`research-claim research-claim-${claim.author} ${highlighted ? "research-claim-highlight" : ""}`}
    >
      {editing ? (
        <div className="research-claim-edit">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void save();
              if (event.key === "Escape") setEditing(false);
            }}
            rows={3}
            autoFocus
            aria-label="Edit claim"
          />
          <div className="research-row">
            <button type="button" className="nav-btn" disabled={saving} onClick={() => void save()}>
              Save
            </button>
            <button type="button" className="nav-btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="research-claim-line">
          <span>{claim.text}</span>
          {claim.author === "reader" && <span className="research-badge research-badge-reader">yours</span>}
          {claim.edited && (
            <span
              className="research-badge research-badge-edited"
              title={claim.original_text ? `Originally: ${claim.original_text}` : undefined}
            >
              edited
            </span>
          )}
          {claim.sent_note_id !== null && (
            <button
              type="button"
              className="research-badge research-badge-board"
              onClick={() => onOpenNote(claim.sent_note_id as number)}
              title="Show this note on the board"
            >
              on board ↗
            </button>
          )}
          {claim.sent_note_id !== null && boardPicker}
          {claim.stale && (
            <span className="research-badge research-badge-muted" title="Not found in the latest extraction">
              not in latest extraction
            </span>
          )}
          {claim.stale && (
            <button
              type="button"
              className="research-link-btn"
              onClick={() => void onKeep(claim.id)}
              title="Keep this Claim and clear the flag (or delete it below)"
            >
              keep
            </button>
          )}
        </div>
      )}
      {!editing && (
        <div className="research-claim-actions">
          {claim.quote && (
            <button type="button" className="research-link-btn" onClick={() => setShowQuote(!showQuote)}>
              {showQuote ? "hide quote" : "quote"}
            </button>
          )}
          {claim.sent_note_id === null && (
            <>
              <button type="button" className="research-link-btn" disabled={sending} onClick={() => void send()}>
                → send to board
              </button>
              {boardPicker}
            </>
          )}
          <button
            type="button"
            className="research-link-btn"
            onClick={() => {
              setDraft(claim.text);
              setEditing(true);
            }}
          >
            edit
          </button>
          {confirmDelete ? (
            <>
              <button type="button" className="research-link-btn research-danger" onClick={() => void onDelete(claim.id)}>
                confirm delete
              </button>
              <button type="button" className="research-link-btn" onClick={() => setConfirmDelete(false)}>
                keep
              </button>
            </>
          ) : (
            <button type="button" className="research-link-btn" onClick={() => setConfirmDelete(true)}>
              delete
            </button>
          )}
        </div>
      )}
      {showQuote && claim.quote && <blockquote className="research-quote">“{claim.quote}”</blockquote>}
    </li>
  );
}
