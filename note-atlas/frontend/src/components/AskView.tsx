import { useRef, useState, type FormEvent } from "react";
import { streamAsk } from "../api";
import type { Citation } from "../types";

const PRESETS = [
  "How do B+ tree leaves differ from internal nodes?",
  "Why does high fanout reduce disk I/O?",
  "What is the capital of France?",
];

type AskViewProps = {
  onSelectSource: (citation: Citation) => void;
};

export function AskView({ onSelectSource }: AskViewProps) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [grounded, setGrounded] = useState<boolean | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function runAsk(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setQuestion(trimmed);
    setAsking(true);
    setError(null);
    setAnswer("");
    setCitations([]);
    setGrounded(null);
    try {
      await streamAsk(
        trimmed,
        {
          onMeta: (meta) => {
            setGrounded(meta.grounded);
            setCitations(meta.citations);
          },
          onToken: (piece) => {
            setAnswer((current) => current + piece);
          },
          onError: (detail) => {
            setError(detail);
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (controller.signal.aborted) {
        return;
      }
      const message = err instanceof Error ? err.message : "Ask failed.";
      setError(message);
    } finally {
      if (abortRef.current === controller) {
        setAsking(false);
      }
    }
  }

  function handleSubmit(event: FormEvent): void {
    event.preventDefault();
    void runAsk(question);
  }

  return (
    <div className="ask-view">
      <section className="ask-main">
        <h2>Ask your notes</h2>
        <form className="ask-form" onSubmit={handleSubmit}>
          <label>
            Question
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              placeholder="Ask something that is in your notes…"
            />
          </label>
          <div className="form-actions">
            <button className="btn" type="submit" disabled={asking || !question.trim()}>
              {asking ? "Asking…" : "Ask"}
            </button>
          </div>
        </form>
        <p className="ask-presets-label">Examples</p>
        <div className="ask-presets">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                void runAsk(preset);
              }}
            >
              {preset}
            </button>
          ))}
        </div>
        {error ? <p className="form-error">{error}</p> : null}
        <p className="ask-answer-label">Answer</p>
        <div
          className={grounded === false ? "ask-answer declined" : "ask-answer"}
          aria-live="polite"
        >
          {answer || (asking ? "…" : "Ask a question to search your notes.")}
        </div>
      </section>
      <aside className="ask-sources" aria-label="Retrieved sources">
        <h2>Sources</h2>
        {citations.length === 0 ? (
          <p className="empty">
            {asking ? "Retrieving…" : "Matching notes and topics appear here."}
          </p>
        ) : (
          <ul>
            {citations.map((citation) => (
              <li key={`${citation.note_id}-${citation.topic_id ?? "note"}`}>
                <button
                  type="button"
                  className="ask-source"
                  onClick={() => onSelectSource(citation)}
                >
                  <span className="ask-source-title">{citation.note_title}</span>
                  <span className="ask-source-topic">
                    {citation.topic_title ?? "Note summary"}
                  </span>
                  <span className="ask-source-score">
                    score {citation.score.toFixed(2)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
