import { Fragment, useState } from "react";
import { ChunkPreviewPanel } from "./ChunkPreviewPanel";
import type { DocumentStatus, FileDocument } from "./types";

type FileTableProps = {
  documents: FileDocument[];
  onDelete: (document: FileDocument) => void;
  onChanged: () => void;
};

const STATUS_CLASS: Record<DocumentStatus, string> = {
  uploaded: "files-badge",
  indexing: "files-badge files-badge-wait",
  indexed: "files-badge files-badge-ok",
  failed: "files-badge files-badge-failed",
};

const COLUMNS = 6;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileTable({ documents, onDelete, onChanged }: FileTableProps) {
  const [previewId, setPreviewId] = useState<number | null>(null);

  if (documents.length === 0) {
    return <p className="files-muted">No files yet. Drop PDFs or .txt files here, or use Add files.</p>;
  }
  return (
    <table className="files-table">
      <thead>
        <tr>
          <th>Name</th>
          <th className="num">Size</th>
          <th className="num">Pages</th>
          <th className="num">Chunks</th>
          <th>Status</th>
          <th aria-label="Actions" />
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => {
          const open = previewId === doc.id;
          return (
            <Fragment key={doc.id}>
              <tr>
                <td className="files-filename">
                  {doc.filename}
                  {doc.encoding && <span className="files-encoding">{doc.encoding}</span>}
                  {doc.status === "failed" && doc.error && <div className="files-row-error">{doc.error}</div>}
                </td>
                <td className="num">{formatBytes(doc.size_bytes)}</td>
                <td className="num">{doc.page_count ?? "—"}</td>
                <td className="num">{doc.chunk_count}</td>
                <td>
                  <span className={STATUS_CLASS[doc.status]}>{doc.status}</span>
                </td>
                <td className="num files-actions">
                  <button
                    type="button"
                    className="files-link-btn"
                    aria-expanded={open}
                    onClick={() => setPreviewId(open ? null : doc.id)}
                  >
                    {open ? "Hide chunks" : "Preview chunks"}
                  </button>
                  <button
                    type="button"
                    className="files-link-btn danger"
                    aria-label={`Delete ${doc.filename}`}
                    onClick={() => onDelete(doc)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
              {open && (
                <tr className="files-preview-row">
                  <td colSpan={COLUMNS}>
                    <ChunkPreviewPanel documentId={doc.id} onExtracted={onChanged} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
