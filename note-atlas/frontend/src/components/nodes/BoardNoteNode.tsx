import { createContext, useContext, useEffect, useRef } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

export type BoardNoteData = {
  title: string;
  source: string;
  rawText: string;
  noteId: number;
  color: string | null;
  z: number;
  text: string;
  editing: boolean;
};

export type BoardNoteNode = Node<BoardNoteData, "boardNote">;

export type BoardSession = {
  startEdit: (nodeId: string) => void;
  updateText: (nodeId: string, text: string) => void;
  commitEdit: (nodeId: string, text: string) => void;
  cutConnection: (connectionId: number) => void;
};

export const BoardSessionContext = createContext<BoardSession | null>(null);

const SIDES: Position[] = [Position.Top, Position.Right, Position.Bottom, Position.Left];

function BoardHandles({ connectable, title }: { connectable: boolean; title: string }) {
  return (
    <>
      {SIDES.map((side) => (
        <span key={side}>
          <Handle
            id={side}
            type="target"
            position={side}
            isConnectable={connectable}
            className="board-handle"
            role="button"
            aria-label={`Connect ${title} ${side}`}
          />
          <Handle
            id={`out-${side}`}
            type="source"
            position={side}
            isConnectable={connectable}
            className="board-handle"
            role="button"
            aria-label={`Link ${title} ${side}`}
          />
        </span>
      ))}
    </>
  );
}

export function BoardNoteNode({ id, data, selected }: NodeProps<BoardNoteNode>) {
  const session = useContext(BoardSessionContext);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const connectable = data.noteId > 0 && !data.editing;
  const className = [
    "map-node",
    "map-node-note",
    "board-note",
    selected ? "selected" : "",
    data.editing ? "editing" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const style = data.color ? { borderColor: data.color } : undefined;

  useEffect(() => {
    if (data.editing && areaRef.current) {
      areaRef.current.focus();
      const end = areaRef.current.value.length;
      areaRef.current.setSelectionRange(end, end);
    }
  }, [data.editing]);

  function commitNow(value: string): void {
    session?.commitEdit(id, value);
  }

  if (data.editing) {
    return (
      <article className={className} style={style} aria-label="Editing note">
        <BoardHandles connectable={false} title={data.title || "note"} />
        <textarea
          ref={areaRef}
          className="board-note-editor nodrag nowheel"
          value={data.text}
          rows={Math.min(12, Math.max(3, data.text.split("\n").length + 1))}
          placeholder="Title on the first line…"
          aria-label="Note text"
          onChange={(event) => session?.updateText(id, event.target.value)}
          onBlur={(event) => commitNow(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              commitNow(event.currentTarget.value);
            }
          }}
        />
      </article>
    );
  }

  const preview = data.text.trim() || data.title;
  const [first, ...rest] = preview.split("\n");
  return (
    <article
      className={className}
      style={style}
      aria-label={`Note ${data.title}`}
      onDoubleClick={(event) => {
        event.stopPropagation();
        session?.startEdit(id);
      }}
    >
      <BoardHandles connectable={connectable} title={data.title || "note"} />
      <p className="map-node-kicker">Note</p>
      <h3>{first || data.title || "Untitled"}</h3>
      {rest.length > 0 ? (
        <p className="board-note-preview">{rest.join(" ").slice(0, 140)}</p>
      ) : (
        <p className="map-node-source">{data.source || "no source"}</p>
      )}
    </article>
  );
}
