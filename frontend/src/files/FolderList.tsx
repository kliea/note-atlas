import { useState, type FormEvent } from "react";
import type { FileFolder } from "./types";

type FolderListProps = {
  folders: FileFolder[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onCreate: (name: string) => Promise<void>;
  onRename: (id: number, name: string) => Promise<void>;
  onDelete: (folder: FileFolder) => void;
};

export function FolderList({ folders, selectedId, onSelect, onCreate, onRename, onDelete }: FolderListProps) {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  async function submitNew(event: FormEvent): Promise<void> {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    await onCreate(name);
    setNewName("");
  }

  async function submitRename(event: FormEvent, id: number): Promise<void> {
    event.preventDefault();
    const name = editName.trim();
    if (name) await onRename(id, name);
    setEditingId(null);
  }

  return (
    <section className="files-folders" aria-label="Folders">
      <h2>Folders</h2>
      <form className="files-row" onSubmit={(event) => void submitNew(event)}>
        <input
          className="files-input"
          placeholder="New folder"
          aria-label="New folder name"
          maxLength={100}
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
        />
        <button type="submit" className="btn-ghost" disabled={!newName.trim()}>
          Create
        </button>
      </form>
      {folders.length === 0 ? (
        <p className="files-muted">No folders yet.</p>
      ) : (
        <ul className="files-folder-list">
          {folders.map((folder) => (
            <li key={folder.id} className={folder.id === selectedId ? "sel" : ""}>
              {editingId === folder.id ? (
                <form className="files-row" onSubmit={(event) => void submitRename(event, folder.id)}>
                  <input
                    className="files-input"
                    aria-label={`Rename ${folder.name}`}
                    maxLength={100}
                    autoFocus
                    value={editName}
                    onChange={(event) => setEditName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") setEditingId(null);
                    }}
                  />
                  <button type="submit" className="btn-ghost">
                    Save
                  </button>
                </form>
              ) : (
                <>
                  <button type="button" className="files-folder-name" onClick={() => onSelect(folder.id)}>
                    {folder.name}
                    <span className="files-muted"> · {folder.document_count}</span>
                  </button>
                  <span className="files-folder-actions">
                    <button
                      type="button"
                      className="files-link-btn"
                      onClick={() => {
                        setEditingId(folder.id);
                        setEditName(folder.name);
                      }}
                    >
                      Rename
                    </button>
                    <button type="button" className="files-link-btn danger" onClick={() => onDelete(folder)}>
                      Delete
                    </button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
