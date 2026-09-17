import { useRef, type FormEvent } from "react";
import type { Topic } from "../types";
import { TopicList } from "./TopicList";

type CaptureFormProps = {
  title: string;
  source: string;
  rawText: string;
  saving: boolean;
  extracting: boolean;
  importing: boolean;
  canExtract: boolean;
  topics: Topic[];
  error: string | null;
  onTitleChange: (value: string) => void;
  onSourceChange: (value: string) => void;
  onRawTextChange: (value: string) => void;
  onSubmit: () => void;
  onExtract: () => void;
  onExport: (format: "json" | "markdown") => void;
  onImportFile: (file: File) => void;
};

export function CaptureForm({
  title,
  source,
  rawText,
  saving,
  extracting,
  importing,
  canExtract,
  topics,
  error,
  onTitleChange,
  onSourceChange,
  onRawTextChange,
  onSubmit,
  onExtract,
  onExport,
  onImportFile,
}: CaptureFormProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit();
  }

  const busy = saving || extracting || importing;

  return (
    <section className="capture">
      <h2>Capture</h2>
      <form className="capture-form" onSubmit={handleSubmit}>
        <label>
          Title
          <input
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            required
            autoComplete="off"
          />
        </label>
        <label>
          Source
          <input
            value={source}
            onChange={(event) => onSourceChange(event.target.value)}
            placeholder="meeting, lecture, …"
            autoComplete="off"
          />
        </label>
        <label className="raw-label">
          Raw notes
          <textarea
            value={rawText}
            onChange={(event) => onRawTextChange(event.target.value)}
            required
            spellCheck={false}
          />
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <div className="form-actions">
          <button type="submit" className="btn" disabled={busy}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || !canExtract}
            onClick={onExtract}
          >
            {extracting ? "Extracting…" : "Extract"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || !canExtract}
            onClick={() => onExport("json")}
          >
            Export JSON
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || !canExtract}
            onClick={() => onExport("markdown")}
          >
            Export Markdown
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            {importing ? "Importing…" : "Import"}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".json,.md,.markdown,application/json,text/markdown"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) {
                onImportFile(file);
              }
            }}
          />
        </div>
      </form>
      <div className="topics">
        <h2>Topics</h2>
        <TopicList topics={topics} extracting={extracting} />
      </div>
    </section>
  );
}
