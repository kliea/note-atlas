import type { NoteSummary } from "../types";

type NoteListProps = {
  notes: NoteSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNew: () => void;
};

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString();
}

export function NoteList({ notes, selectedId, onSelect, onNew }: NoteListProps) {
  return (
    <aside className="note-list">
      <div className="note-list-header">
        <h2>Notes</h2>
        <button type="button" className="btn btn-ghost" onClick={onNew}>
          New
        </button>
      </div>
      {notes.length === 0 ? (
        <p className="empty">No notes yet.</p>
      ) : (
        <ul>
          {notes.map((note) => (
            <li key={note.id}>
              <button
                type="button"
                className={note.id === selectedId ? "note-item selected" : "note-item"}
                onClick={() => onSelect(note.id)}
              >
                <span className="note-item-title">{note.title}</span>
                <span className="note-item-meta">
                  {note.source || "no source"} · {formatWhen(note.created_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
