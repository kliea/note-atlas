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
  encoding: string | null;
};

export type SkippedUpload = {
  filename: string;
  reason: string;
};

export type UploadResult = {
  added: FileDocument[];
  skipped: SkippedUpload[];
};

export type ChunkPreview = {
  idx: number;
  text: string;
  page_start: number;
  char_start: number;
};

export type ChunkPreviewResult = {
  document_id: number;
  page_count: number;
  chunk_size: number;
  overlap: number;
  total_chunks: number;
  chunks: ChunkPreview[];
};

export type JobStatus = "queued" | "running" | "done" | "failed";

export type FileJob = {
  id: number;
  folder_id: number;
  status: JobStatus;
  done: number;
  total: number;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type FolderIndexStatus = {
  folder_id: number;
  name: string;
  chunk_count: number;
};

export type IndexStatus = {
  total_chunks: number;
  folders: FolderIndexStatus[];
};

export type RetrievedChunk = {
  id: string;
  document_id: number;
  folder_id: number;
  filename: string;
  page_start: number;
  chunk_idx: number;
  text: string;
  score: number;
  retriever: "vector" | "bm25" | "both";
};

export type FileAsk = {
  id: number;
  question: string;
  answer: string;
  folder_ids: number[] | null;
  chunks: RetrievedChunk[];
  model: string;
  created_at: string;
  sources: string[] | null;
};

export type FilesAskDone = {
  empty: string | null;
  chunks: RetrievedChunk[];
  ask: FileAsk | null;
  retrieval_query: string | null;
};

export type FilesSettings = {
  accepted: string[];
  default_model: string;
  top_k: number;
  show_sources: boolean;
  hybrid: boolean;
  memory_turns: number;
  model_picker: boolean;
  score_threshold: number | null;
};

export type ModelList = {
  default: string;
  models: string[];
  error: string | null;
};
