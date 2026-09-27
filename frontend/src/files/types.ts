// Files pipeline (lab RAG) API shapes; mirror backend/app/files/models.py.

export type FileFolder = {
  id: number;
  name: string;
  created_at: string;
  document_count: number;
  chunk_count: number;
};

export type DocumentStatus = "uploaded" | "indexing" | "indexed" | "failed";

export type FileDocument = {
  id: number;
  folder_id: number;
  filename: string;
  mime: string;
  size_bytes: number;
  sha256: string;
  page_count: number | null;
  chunk_count: number;
  status: DocumentStatus;
  error: string | null;
  indexed_at: string | null;
  created_at: string;
};

export type SkippedUpload = {
  filename: string;
  reason: string;
};

export type UploadResult = {
  added: FileDocument[];
  skipped: SkippedUpload[];
};
