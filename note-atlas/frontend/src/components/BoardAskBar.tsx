import { useEffect, useRef, type FormEvent } from "react";
import { useReactFlow, useStore } from "@xyflow/react";

type BoardAskBarProps = {
  origin: { x: number; y: number };
  noteIds: number[];
  onSubmit: (question: string) => void;
  onClose: () => void;
};

export function BoardAskBar({ origin, noteIds, onSubmit, onClose }: BoardAskBarProps) {
  const { flowToScreenPosition } = useReactFlow();
  useStore((state) => state.transform);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const screen = flowToScreenPosition(origin);
  const canvas = document.querySelector(".board-canvas");
  const box = canvas instanceof HTMLElement ? canvas.getBoundingClientRect() : null;
  const left = box ? screen.x - box.left : screen.x;
  const top = box ? screen.y - box.top : screen.y;
  const scope =
    noteIds.length === 0
      ? "Asking the whole board"
      : noteIds.length === 1
        ? "Asking 1 note"
        : `Asking ${noteIds.length} notes`;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function submitQuestion(): void {
    const question = inputRef.current?.value.trim() ?? "";
    if (!question) {
      return;
    }
    onSubmit(question);
  }

  function handleSubmit(event: FormEvent): void {
    event.preventDefault();
    submitQuestion();
  }

  return (
    <form
      className="board-ask"
      style={{ left, top }}
      aria-label="Ask notes"
      onSubmit={handleSubmit}
      onMouseDown={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <p className="board-ask-scope">{scope}</p>
      <textarea
        ref={inputRef}
        className="board-ask-input"
        rows={2}
        placeholder="Ask something in these notes…"
        aria-label="Question"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          }
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submitQuestion();
          }
        }}
      />
      <div className="board-ask-actions">
        <button className="btn" type="submit">
          Ask
        </button>
        <button className="btn btn-ghost" type="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}
