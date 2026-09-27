import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import {
  createFileFolder,
  deleteFileDocument,
  deleteFileFolder,
  fetchFileDocuments,
  fetchFileFolders,
  renameFileFolder,
  uploadFileDocuments,
} from "../api";
import { FileTable } from "./FileTable";
import { FolderList } from "./FolderList";
import type { FileDocument, FileFolder } from "./types";
import "./files.css";

const SELECTED_KEY = "files.selectedFolder";

function readSelected(): number | null {
  try {
    const raw = window.localStorage.getItem(SELECTED_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

function saveSelected(id: number | null): void {
  try {
    if (id === null) window.localStorage.removeItem(SELECTED_KEY);
    else window.localStorage.setItem(SELECTED_KEY, String(id));
  } catch {
    // Remembering the folder is a convenience only.
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function FilesView() {
  const [folders, setFolders] = useState<FileFolder[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(readSelected);
  const [documents, setDocuments] = useState<FileDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = folders.find((folder) => folder.id === selectedId) ?? null;
  // Only a folder that exists is loaded, so a stale remembered id never hits the API.
  const selectedFolderId = selected?.id ?? null;

  const loadFolders = useCallback(async (): Promise<FileFolder[]> => {
    const list = await fetchFileFolders();
    setFolders(list);
    return list;
  }, []);

  function select(id: number | null): void {
    setSelectedId(id);
    saveSelected(id);
    setNotice(null);
    setError(null);
  }

  useEffect(() => {
    void loadFolders()
      .then((list) => {
        if (!list.some((folder) => folder.id === readSelected())) select(list[0]?.id ?? null);
      })
      .catch((err: unknown) => setError(message(err)));
  }, [loadFolders]);

  useEffect(() => {
    if (selectedFolderId === null) {
      setDocuments([]);
      return;
    }
    let cancelled = false;
    void fetchFileDocuments(selectedFolderId)
      .then((docs) => {
        if (!cancelled) setDocuments(docs);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(message(err));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFolderId]);

  async function refresh(folderId: number): Promise<void> {
    const [, docs] = await Promise.all([loadFolders(), fetchFileDocuments(folderId)]);
    setDocuments(docs);
  }

  async function createFolder(name: string): Promise<void> {
    try {
      const folder = await createFileFolder(name);
      await loadFolders();
      select(folder.id);
    } catch (err) {
      setError(message(err));
    }
  }

  async function renameFolder(id: number, name: string): Promise<void> {
    try {
      await renameFileFolder(id, name);
      await loadFolders();
    } catch (err) {
      setError(message(err));
    }
  }

  async function removeFolder(folder: FileFolder): Promise<void> {
    const files = folder.document_count === 1 ? "1 file" : `${folder.document_count} files`;
    if (!window.confirm(`Delete folder "${folder.name}" and its ${files}? This cannot be undone.`)) return;
    try {
      await deleteFileFolder(folder.id);
      const list = await loadFolders();
      if (folder.id === selectedId) select(list[0]?.id ?? null);
    } catch (err) {
      setError(message(err));
    }
  }

  async function removeDocument(doc: FileDocument): Promise<void> {
    if (!window.confirm(`Delete "${doc.filename}"?`)) return;
    try {
      await deleteFileDocument(doc.id);
      await refresh(doc.folder_id);
    } catch (err) {
      setError(message(err));
    }
  }

  async function upload(files: File[]): Promise<void> {
    if (selectedFolderId === null || files.length === 0) return;
    setUploading(true);
    setNotice(null);
    setError(null);
    try {
      const result = await uploadFileDocuments(selectedFolderId, files);
      const parts = [`Added ${result.added.length} ${result.added.length === 1 ? "file" : "files"}.`];
      if (result.skipped.length > 0) {
        parts.push(`Skipped ${result.skipped.map((s) => `${s.filename} (${s.reason})`).join(", ")}.`);
      }
      setNotice(parts.join(" "));
      await refresh(selectedFolderId);
    } catch (err) {
      setError(message(err));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLElement>): void {
    event.preventDefault();
    setDragging(false);
    void upload(Array.from(event.dataTransfer.files));
  }

  return (
    <div className="files">
      <FolderList
        folders={folders}
        selectedId={selectedId}
        onSelect={select}
        onCreate={createFolder}
        onRename={renameFolder}
        onDelete={(folder) => void removeFolder(folder)}
      />
      <section
        className={`files-main ${dragging ? "files-dragging" : ""}`}
        aria-label="Files"
        onDragOver={(event) => {
          if (selected && event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={(event) => {
          if (event.currentTarget === event.target) setDragging(false);
        }}
        onDrop={onDrop}
      >
        {selected === null ? (
          <p className="files-muted">Create a folder to start adding files.</p>
        ) : (
          <>
            <div className="files-row files-header">
              <h2 className="files-title">{selected.name}</h2>
              <button
                type="button"
                className="btn"
                disabled={uploading}
                onClick={() => inputRef.current?.click()}
              >
                {uploading ? "Uploading…" : "Add files"}
              </button>
              <input
                ref={inputRef}
                type="file"
                accept="application/pdf,.pdf,text/plain,.txt"
                multiple
                hidden
                onChange={(event) => void upload(Array.from(event.target.files ?? []))}
              />
            </div>
            <p className="files-muted">PDF and .txt files. Drop them anywhere in this panel.</p>
            {notice && (
              <p className="files-notice" role="status">
                {notice}
              </p>
            )}
            <FileTable
              documents={documents}
              onDelete={(doc) => void removeDocument(doc)}
              onChanged={() => void refresh(selected.id).catch((err: unknown) => setError(message(err)))}
            />
          </>
        )}
        {error && (
          <p className="files-error" role="alert">
            {error}
          </p>
        )}
      </section>
    </div>
  );
}
