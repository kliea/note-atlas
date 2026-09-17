import { type Node, type NodeProps } from "@xyflow/react";

export type BoardNoteData = {
  title: string;
  source: string;
  noteId: number;
  color: string | null;
  z: number;
};

export type BoardNoteNode = Node<BoardNoteData, "boardNote">;

export function BoardNoteNode({ data, selected }: NodeProps<BoardNoteNode>) {
  const className = ["map-node", "map-node-note", "board-note", selected ? "selected" : ""]
    .filter(Boolean)
    .join(" ");
  const style = data.color
    ? { borderColor: data.color, ["--note-accent" as string]: data.color }
    : undefined;
  return (
    <article
      className={className}
      style={style}
      aria-label={`Note ${data.title}`}
    >
      <p className="map-node-kicker">Note</p>
      <h3>{data.title}</h3>
      <p className="map-node-source">{data.source || "no source"}</p>
    </article>
  );
}
