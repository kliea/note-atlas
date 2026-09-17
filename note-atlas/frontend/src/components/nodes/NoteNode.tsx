import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

export type NoteNodeData = {
  title: string;
  source: string;
  noteId: number;
};

export type NoteMapNode = Node<NoteNodeData, "note">;

const SIDES: Position[] = [Position.Top, Position.Right, Position.Bottom, Position.Left];

export function NoteNode({ data, selected }: NodeProps<NoteMapNode>) {
  const className = [
    "map-node",
    "map-node-note",
    selected ? "selected" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={className}>
      {SIDES.map((side) => (
        <Handle key={side} id={side} type="source" position={side} />
      ))}
      <p className="map-node-kicker">Note</p>
      <h3>{data.title}</h3>
      <p className="map-node-source">{data.source || "no source"}</p>
    </div>
  );
}
