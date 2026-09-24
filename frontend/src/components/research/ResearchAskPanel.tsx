import { useEffect, useRef, useState } from "react";
import { createNote, streamResearchAsk } from "../../api";
import { loadBoardCentre } from "../../boardCentre";
import type { ResearchCitation } from "../../types";

// Board card size, mirrored from BoardView.tsx, to centre a sent answer on the last view.
const NOTE_CARD_WIDTH = 240;
const NOTE_CARD_HEIGHT = 120;

type ResearchAskPanelProps = {
  studyIds: number[];
  scopeLabel: string;
  onCite: (citation: ResearchCitation) => void;
  onClose: () => void;
};

type Answer = {
  question: string;
  text: string;
  grounded: boolean | null;
  citations: ResearchCitation[];
  done: boolean;
  error: string | null;
  noteId: number | null;
};

export function ResearchAskPanel({ studyIds, scopeLabel, onCite, onClose }: ResearchAskPanelProps) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    return () => abortRef.current?.abort();
  }, []);

  async function ask(): Promise<void> {
    const q = question.trim();
    if (!q) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setAnswer({ question: q, text: "", grounded: null, citations: [], done: false, error: null, noteId: null });
    const update = (patch: Partial<Answer>) => setAnswer((current) => (current ? { ...current, ...patch } : current));
    try {
      await streamResearchAsk(
        q,
        studyIds,
        {
          onMeta: (meta) => update({ grounded: meta.grounded, citations: meta.citations }),
          onToken: (text) => setAnswer((current) => (current ? { ...current, text: current.text + text } : current)),
          onError: (detail) => update({ error: detail }),
        },
        controller.signal,
      );
      update({ done: true });
    } catch (err) {
      if (!controller.signal.aborted) update({ error: err instanceof Error ? err.message : String(err), done: true });
    }
  }

  async function sendToBoard(): Promise<void> {
    if (!answer) return;
    const sources = answer.citations.map((c) => `[${c.number}] ${c.study_title} · ${c.label}`).join("\n");
    const centre = loadBoardCentre();
    try {
      const note = await createNote({
        title: answer.question,
        source: "ask",
        raw_text: sources ? `${answer.text.trim()}\n\nSources:\n${sources}` : answer.text.trim(),
        ...(centre ? { x: centre.x - NOTE_CARD_WIDTH / 2, y: centre.y - NOTE_CARD_HEIGHT / 2 } : {}),
      });
      setAnswer((current) => (current ? { ...current, noteId: note.id } : current));
    } catch (err) {
      setAnswer((current) => (current ? { ...current, error: err instanceof Error ? err.message : String(err) } : current));
    }
  }

  return (
    <section className="research-ask" aria-label="Ask across Papers">
      <form
        className="research-row"
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <input
          ref={inputRef}
          className="research-search"
          type="search"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onClose();
          }}
          placeholder="Ask across Papers, e.g. What limitations do these papers share?"
          aria-label="Question"
        />
        <button type="submit" className="nav-btn" disabled={!question.trim()}>
          Ask
        </button>
        <button type="button" className="research-link-btn" onClick={onClose} aria-label="Close Ask">
          ×
        </button>
      </form>
      <p className="research-muted research-ask-scope">
        Over the Extractions and Claims of {scopeLabel}. Select Papers in the Library to narrow it.
      </p>
      {answer && (
        <div className="research-ask-answer">
          {answer.error ? (
            <p className="research-error" role="alert">
              {answer.error}
            </p>
          ) : (
            <p className={answer.grounded === false ? "research-muted" : undefined}>
              {answer.text || (answer.done ? "" : "Thinking…")}
            </p>
          )}
          {answer.citations.length > 0 && (
            <ol className="research-ask-citations">
              {answer.citations.map((citation) => (
                <li key={citation.number} value={citation.number}>
                  <button type="button" className="research-link-btn" onClick={() => onCite(citation)}>
                    {citation.study_title} · {citation.label}
                  </button>
                  <span className="research-muted"> — {citation.text}</span>
                </li>
              ))}
            </ol>
          )}
          {answer.done && answer.grounded && !answer.error && (
            <div className="research-row">
              {answer.noteId === null ? (
                <button type="button" className="research-link-btn" onClick={() => void sendToBoard()}>
                  → send to board
                </button>
              ) : (
                <span className="research-badge research-badge-board">on board</span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
