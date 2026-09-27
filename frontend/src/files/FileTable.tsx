import type { DocumentStatus, FileDocument } from "./types";

type FileTableProps = {
  documents: FileDocument[];
  onDelete: (document: FileDocument) => void;
};

const STATUS_CLASS: Record<DocumentStatus, string> = {
  uploaded: "files-badge",
  indexing: "files-badge files-badge-wait",
  indexed: "files-badge files-badge-ok",
  failed: "files-badge files-badge-failed",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileTable({ documents, onDelete }: FileTableProps) {
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
        {documents.map((doc) => (
          <tr key={doc.id}>
            <td className="files-filename">{doc.filename}</td>
            <td className="num">{formatBytes(doc.size_bytes)}</td>
            <td className="num">{doc.page_count ?? "—"}</td>
            <td className="num">{doc.chunk_count}</td>
            <td>
              <span className={STATUS_CLASS[doc.status]} title={doc.error ?? undefined}>
                {doc.status}
              </span>
            </td>
            <td className="num">
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
        ))}
      </tbody>
    </table>
  );
}
