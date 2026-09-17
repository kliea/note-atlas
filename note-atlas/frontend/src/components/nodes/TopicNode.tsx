import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

export type TopicNodeData = {
  title: string;
  topicId: number;
  noteId: number;
};

export type TopicMapNode = Node<TopicNodeData, "topic">;

const SIDES: Position[] = [Position.Top, Position.Right, Position.Bottom, Position.Left];

export function TopicNode({ data, selected }: NodeProps<TopicMapNode>) {
  return (
    <div className={selected ? "map-node map-node-topic selected" : "map-node map-node-topic"}>
      {SIDES.map((side) => (
        <Handle key={`in-${side}`} id={side} type="target" position={side} />
      ))}
      {SIDES.map((side) => (
        <Handle key={`out-${side}`} id={`out-${side}`} type="source" position={side} />
      ))}
      <p className="map-node-kicker">Topic</p>
      <h3>{data.title}</h3>
    </div>
  );
}
