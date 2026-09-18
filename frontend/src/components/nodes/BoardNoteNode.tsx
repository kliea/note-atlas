import { useContext, useEffect, useRef, useState } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { ExtractStatus, Point, Topic } from "../../types";
import { BoardSessionContext, type BoardSession } from "./BoardSession";

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
  const points = pointsForCard(data.topics);
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
        {thinking ? "Extracting" : data.source === "ask" ? "Answer" : "Note"}
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
          {points.map((point) => (
            <li key={point.id}>
              <span className="board-note-point-text">{point.text}</span>
              <PointContext
                noteId={data.noteId}
                point={point}
                session={session}
              />
            </li>
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

function isVisibleContext(point: Point): boolean {
  return Boolean(
    point.context &&
      (point.context_status === "suggested" || point.context_status === "accepted"),
  );
}

function pointsForCard(topics: Topic[]): Point[] {
  return topics.flatMap((topic) => topic.points).slice(0, 3);
}

function PointContext({
  noteId,
  point,
  session,
}: {
  noteId: number;
  point: Point;
  session: BoardSession | null;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(point.context ?? "");
  if (!isVisibleContext(point) || !point.context) {
    return null;
  }
  const suggested = point.context_status === "suggested";

  function stop(event: { stopPropagation: () => void }): void {
    event.stopPropagation();
  }

  return (
    <div className="board-note-context" role="note" aria-label="AI context">
      <span className="board-note-context-tag">AI context</span>
      {editing ? (
        <textarea
          className="board-note-context-editor nodrag nopan nowheel"
          value={draft}
          rows={3}
          aria-label="Edit AI context"
          onPointerDown={stop}
          onDoubleClick={stop}
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : (
        <p>{point.context}</p>
      )}
      {suggested ? (
        <div className="board-note-context-actions nodrag nopan" onPointerDown={stop}>
          {editing ? (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                const next = draft.trim();
                if (next) {
                  session?.savePointContext(noteId, point.id, next);
                }
                setEditing(false);
              }}
            >
              Save
            </button>
          ) : (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => session?.acceptPointContext(noteId, point.id)}
            >
              Accept
            </button>
          )}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              setDraft(point.context ?? "");
              setEditing((open) => !open);
            }}
          >
            {editing ? "Cancel" : "Edit"}
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => session?.dismissPointContext(noteId, point.id)}
          >
            Dismiss
          </button>
        </div>
      ) : null}
    </div>
  );
}
