import { Background, ReactFlow, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const nodes: Node[] = [
  {
    id: "1",
    position: { x: 80, y: 80 },
    data: { label: "Fixture note" },
  },
];

export function CanvasBoard() {
  return (
    <div className="board">
      <ReactFlow nodes={nodes} fitView>
        <Background />
      </ReactFlow>
    </div>
  );
}
