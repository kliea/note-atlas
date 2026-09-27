import { useEffect, useRef, useState } from "react";
import { fetchChunkPreview } from "../api";
import type { ChunkPreviewResult } from "./types";

const PREVIEW_LIMIT = 20;

type ChunkPreviewPanelProps = {
  documentId: number;
  onExtracted: () => void;
};

// Debug view: the chunks this file would be indexed as, before any embedding.
export function ChunkPreviewPanel({ documentId, onExtracted }: ChunkPreviewPanelProps) {
  const [preview, setPreview] = useState<ChunkPreviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Held in a ref so a new callback identity never re-runs extraction.
  const onExtractedRef = useRef(onExtracted);
  onExtractedRef.current = onExtracted;

  useEffect(() => {
    let cancelled = false;
    void fetchChunkPreview(documentId, PREVIEW_LIMIT)
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      // Extraction records the page count, or marks the file failed; refresh the row either way.
      .finally(() => {
        if (!cancelled) onExtractedRef.current();
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  if (error) return <p className="files-error">{error}</p>;
  if (!preview) return <p className="files-muted">Extracting text…</p>;
  return (
    <div className="files-preview">
      <p className="files-muted">
        {preview.total_chunks} chunks · {preview.chunk_size} characters each, overlap {preview.overlap}
        {preview.total_chunks > preview.chunks.length && ` · showing the first ${preview.chunks.length}`}
      </p>
      <ol className="files-chunks">
        {preview.chunks.map((chunk) => (
          <li key={chunk.idx}>
            <div className="files-chunk-meta">
              #{chunk.idx} · p.{chunk.page_start} · chars {chunk.char_start}–{chunk.char_start + chunk.text.length}
            </div>
            <pre className="files-chunk-text">{chunk.text}</pre>
          </li>
        ))}
      </ol>
    </div>
  );
}
