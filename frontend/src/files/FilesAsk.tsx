import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { clearFileAsks, fetchFileAsks, streamFilesAsk } from "../api";
import type { FileAsk, FileFolder, RetrievedChunk } from "./types";

type Scope = "folder" | "all";

type FilesAskProps = {
  folders: FileFolder[];
  folder: FileFolder | null;
};

type Current = {
  question: string;
  text: string;
  chunks: RetrievedChunk[];
  done: boolean;
  empty: string | null;
  error: string | null;
};

function sourceLabel(chunk: RetrievedChunk): string {
  return `${chunk.filename} · p.${chunk.page_start}`;
}

function ChunkList({ chunks }: { chunks: RetrievedChunk[] }) {
  return (
    <div className="files-chunks">
      {chunks.map((chunk, index) => (
        <details key={chunk.id} className="files-source">
          <summary>
            Chunk {index + 1} · {sourceLabel(chunk)}
            <span className="files-muted"> · score {chunk.score.toFixed(2)}</span>
          </summary>
          <pre className="files-chunk-text">{chunk.text}</pre>
        </details>
      ))}
    </div>
  );
}

// Ask Questions over the Files index: streamed answer, its retrieved chunks, and Chat History.
export function FilesAsk({ folders, folder }: FilesAskProps) {
  const [scope, setScope] = useState<Scope>("folder");
  const [question, setQuestion] = useState("");
  const [current, setCurrent] = useState<Current | null>(null);
  const [history, setHistory] = useState<FileAsk[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const effectiveScope: Scope = folder === null ? "all" : scope;
  const busy = current !== null && !current.done;

  useEffect(() => {
    void fetchFileAsks()
      .then(setHistory)
      .catch((err: unknown) => setHistoryError(err instanceof Error ? err.message : String(err)));
    return () => abortRef.current?.abort();
  }, []);

  function scopeLabel(folderIds: number[] | null): string {
    if (!folderIds) return "all folders";
    return folderIds.map((id) => folders.find((f) => f.id === id)?.name ?? `folder ${id}`).join(", ");
  }

  async function ask(event?: FormEvent): Promise<void> {
    event?.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const folderIds = effectiveScope === "folder" && folder ? [folder.id] : null;
    setCurrent({ question: q, text: "", chunks: [], done: false, empty: null, error: null });
    const update = (patch: (prev: Current) => Current): void =>
      setCurrent((prev) => (prev === null ? prev : patch(prev)));
    try {
      await streamFilesAsk(
        q,
        folderIds,
        {
          onToken: (text) => update((prev) => ({ ...prev, text: prev.text + text })),
          onDone: (done) => {
            update((prev) => ({ ...prev, chunks: done.chunks, empty: done.empty, done: true }));
            const saved = done.ask;
            if (saved) setHistory((prev) => [saved, ...prev.filter((h) => h.id !== saved.id)]);
          },
          onError: (detail) => update((prev) => ({ ...prev, error: detail, done: true })),
        },
        controller.signal,
      );
      update((prev) => ({ ...prev, done: true }));
      setQuestion("");
    } catch (err) {
      if (controller.signal.aborted) return;
      update((prev) => ({ ...prev, error: err instanceof Error ? err.message : String(err), done: true }));
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  }

  async function clearHistory(): Promise<void> {
    if (!window.confirm("Clear the Files chat history?")) return;
    try {
      await clearFileAsks();
      setHistory([]);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section className="files-ask" aria-label="Ask Questions">
      <h3 className="files-heading">Ask Questions</h3>
      <form className="files-ask-form" onSubmit={(event) => void ask(event)}>
        <div className="files-row files-scope" role="radiogroup" aria-label="Scope">
          <label>
            <input
              type="radio"
              name="files-scope"
              checked={effectiveScope === "folder"}
              disabled={folder === null}
              onChange={() => setScope("folder")}
            />
            This folder{folder ? ` (${folder.name})` : ""}
          </label>
          <label>
            <input
              type="radio"
              name="files-scope"
              checked={effectiveScope === "all"}
              onChange={() => setScope("all")}
            />
            All folders
          </label>
        </div>
        <textarea
          aria-label="Question"
          placeholder="Ask a question about the uploaded documents"
          rows={2}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="btn" disabled={busy || !question.trim()}>
          {busy ? "Answering…" : "Ask"}
        </button>
      </form>

      {current && (
        <div className="files-answer" aria-live="polite">
          <p className="files-question">{current.question}</p>
          {current.error ? (
            <p className="files-error">{current.error}</p>
          ) : current.empty ? (
            <p className="files-notice">{current.empty}</p>
          ) : (
            <p className="files-answer-text">{current.text || (current.done ? "" : "Thinking…")}</p>
          )}
          {current.done && !current.error && !current.empty && (
            <>
              <p className="files-muted">Retrieved {current.chunks.length} chunks.</p>
              {current.chunks.length > 0 && (
                <>
                  <h4 className="files-subheading">Retrieved Context</h4>
                  <ChunkList chunks={current.chunks} />
                </>
              )}
            </>
          )}
        </div>
      )}

      <div className="files-row files-header">
        <h3 className="files-heading">Chat History</h3>
        {history.length > 0 && (
          <button type="button" className="files-link-btn danger" onClick={() => void clearHistory()}>
            Clear history
          </button>
        )}
      </div>
      {historyError && <p className="files-error">{historyError}</p>}
      {history.length === 0 ? (
        <p className="files-muted">No questions yet.</p>
      ) : (
        <ol className="files-history">
          {history.map((item) => (
            <li key={item.id}>
              <p className="files-question">{item.question}</p>
              <p className="files-answer-text">{item.answer}</p>
              <p className="files-muted">
                {item.model} · {scopeLabel(item.folder_ids)} · {new Date(item.created_at).toLocaleString()}
              </p>
              {item.chunks.length > 0 && (
                <details className="files-source">
                  <summary>
                    Sources: {Array.from(new Set(item.chunks.map(sourceLabel))).join("; ")}
                  </summary>
                  <ChunkList chunks={item.chunks} />
                </details>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
