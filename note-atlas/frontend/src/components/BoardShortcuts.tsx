const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: "N", action: "New note at the view center" },
  { keys: "Enter", action: "Edit the selected note" },
  { keys: "Esc", action: "Close ask, shortcuts, or the editor" },
  { keys: "Arrow keys", action: "Nudge the selected note (Shift for a larger step)" },
  { keys: "Shift-drag", action: "Lasso notes" },
  { keys: "Shift-click", action: "Add a note to the selection" },
  { keys: "L", action: "Link two selected notes" },
  { keys: "/", action: "Ask, scoped to the lasso if any" },
  { keys: "?", action: "Show this shortcuts list" },
  { keys: "Backspace", action: "Delete the selected note" },
  { keys: "⌘Z / Ctrl+Z", action: "Undo" },
  { keys: "⇧⌘Z / Ctrl+Shift+Z", action: "Redo" },
  { keys: "Double-click canvas", action: "Write a note in place" },
  { keys: "Paste", action: "Drop clipboard text as a note" },
];

type BoardShortcutsProps = {
  onClose: () => void;
};

export function BoardShortcuts({ onClose }: BoardShortcutsProps) {
  return (
    <div
      className="board-shortcuts-scrim"
      role="presentation"
      onClick={onClose}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
      <div
        className="board-shortcuts"
        role="dialog"
        aria-modal="true"
        aria-labelledby="board-shortcuts-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="board-shortcuts-title">Shortcuts</h2>
        <dl>
          {SHORTCUTS.map((item) => (
            <div key={item.keys} className="board-shortcuts-row">
              <dt>
                <kbd>{item.keys}</kbd>
              </dt>
              <dd>{item.action}</dd>
            </div>
          ))}
        </dl>
        <button type="button" className="btn" onClick={onClose} autoFocus>
          Close
        </button>
      </div>
    </div>
  );
}
