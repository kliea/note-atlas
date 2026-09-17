import { createContext, useContext, useEffect, useRef } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { ExtractStatus, Topic } from "../../types";

export type BoardNoteData = {
  title: string;
  source: string;
  rawText: string;
  noteId: number;
  color: string | null;
  z: number;
  text: string;
  editing: boolean;
  extractStatus: ExtractStatus;
  topics: Topic[];
};

export type BoardNoteNode = Node<BoardNoteData, "boardNote">;

export type BoardSession = {
  startEdit: (nodeId: string) => void;
  updateText: (nodeId: string, text: string) => void;
  commitEdit: (nodeId: string, text: string) => void;
  cutConnection: (connectionId: number) => void;
  acceptSuggestion: (fromId: number, toId: number) => void;
  dismissSuggestion: (fromId: number, toId: number) => void;
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
  const thinking = data.extractStatus === "pending" || data.extractStatus === "running";
  const className = [
    "map-node",
    "map-node-note",
    "board-note",
    selected ? "selected" : "",
    data.editing ? "editing" : "",
    thinking ? "thinking" : "",
    data.source === "ask" ? "answer" : "",
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
  const tags = uniqueTags(data.topics);
  const points = data.topics.flatMap((topic) => topic.points.map((point) => point.text));
  return (
    <article
      className={className}
      style={style}
      aria-label={`Note ${data.title}`}
      aria-selected={selected}
      onDoubleClick={(event) => {
        event.stopPropagation();
        session?.startEdit(id);
      }}
    >
      <BoardHandles connectable={connectable} title={data.title || "note"} />
      <p className="map-node-kicker">
        {thinking ? "Thinking" : data.source === "ask" ? "Answer" : "Note"}
      </p>
      <h3>{first || data.title || "Untitled"}</h3>
      {rest.length > 0 ? (
        <p className="board-note-preview">
          {rest.join(" ").slice(0, data.source === "ask" ? 480 : 140)}
        </p>
      ) : data.source === "ask" && data.rawText && data.rawText !== first ? (
        <p className="board-note-preview">{data.rawText.slice(0, 480)}</p>
      ) : data.source === "ask" ? null : (
        <p className="map-node-source">{data.source || "no source"}</p>
      )}
      {points.length > 0 ? (
        <ul className="board-note-points">
          {points.slice(0, 3).map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      ) : null}
      {tags.length > 0 ? (
        <ul className="board-note-tags">
          {tags.slice(0, 6).map((tag) => (
            <li key={tag}>{tag}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function uniqueTags(topics: Topic[]): string[] {
  const tags: string[] = [];
  for (const topic of topics) {
    for (const item of topic.tags) {
      if (!tags.includes(item.tag)) {
        tags.push(item.tag);
      }
    }
  }
  return tags;
}
