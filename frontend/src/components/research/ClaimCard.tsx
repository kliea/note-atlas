import { useEffect, useRef, useState } from "react";
import type { Claim } from "../../types";

type ClaimCardProps = {
  claim: Claim;
  onEdit: (id: number, text: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onKeep: (id: number) => Promise<void>;
  onSend: (id: number) => Promise<void>;
  onOpenNote: (noteId: number) => void;
  highlighted: boolean;
};

export function ClaimCard({ claim, onEdit, onDelete, onKeep, onSend, onOpenNote, highlighted }: ClaimCardProps) {
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
    setSending(true);
    try {
      await onSend(claim.id);
    } finally {
      setSending(false);
    }
  }

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
            <button type="button" className="research-link-btn" disabled={sending} onClick={() => void send()}>
              → send to board
            </button>
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
