import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type ColorMode,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { StudyDetail, StudyState } from "../../types";

// Columns left → right: older work feeds newer work (docs/specs/research-track.md, "UI").
const COLUMN_GAP = 300;
const ROW_GAP = 110;
const MAX_PARENTS = 5;
const MAX_SIBLINGS = 5;
const ANCESTORS_PER_HOP = 3;

type StudyNodeData = { title: string; year: number | null; state: StudyState; role: string; focus: boolean };

function StudyNode({ data }: NodeProps<Node<StudyNodeData>>) {
  return (
    <div className={`research-node research-node-${data.state} ${data.focus ? "focus" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="research-node-role">{data.role}</div>
      <div className="research-node-title">{data.title}</div>
      <div className="research-muted">
        {data.year ?? "—"} · {data.state === "paper" ? "Paper" : "Lead"}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { study: StudyNode };

type Column = { role: string; items: { id: number; title: string; year: number | null; state: StudyState }[] };

type LineageGraphProps = {
  detail: StudyDetail;
  colorMode: ColorMode;
  onOpen: (studyId: number) => void;
};

export function LineageGraph({ detail, colorMode, onOpen }: LineageGraphProps) {
  const [picked, setPicked] = useState<number | null>(null);

  const { nodes, edges, byId } = useMemo(() => {
    const parents = detail.parents.filter((p) => p.is_parent).slice(0, MAX_PARENTS);
    const hop = (n: number) => detail.ancestors.filter((a) => a.hop === n).slice(0, ANCESTORS_PER_HOP);
    const [hop1, hop2] = [hop(1), hop(2)];
    const siblings = detail.siblings.slice(0, MAX_SIBLINGS);
    const columns: Column[] = [
      { role: "Ancestor · 2 hops", items: hop2.map((a) => ({ ...a, id: a.study_id })) },
      { role: "Ancestor", items: hop1.map((a) => ({ ...a, id: a.study_id })) },
      { role: "Parent", items: parents.map((p) => ({ ...p, id: p.study_id })) },
      { role: "This paper", items: [{ id: detail.id, title: detail.title, year: detail.year, state: detail.state }] },
      { role: "Sibling", items: siblings.map((s) => ({ ...s, id: s.study_id })) },
    ].filter((column) => column.items.length > 0);

    const ns: Node<StudyNodeData>[] = [];
    const seen = new Map<number, Column["items"][number] & { role: string }>();
    columns.forEach((column, index) => {
      column.items.forEach((item, row) => {
        if (seen.has(item.id)) return;
        seen.set(item.id, { ...item, role: column.role });
        ns.push({
          id: String(item.id),
          type: "study",
          position: { x: index * COLUMN_GAP, y: (row - (column.items.length - 1) / 2) * ROW_GAP },
          data: { title: item.title, year: item.year, state: item.state, role: column.role, focus: item.id === detail.id },
        });
      });
    });

    const es: Edge[] = [];
    const link = (from: number, to: number, mentions = 0) => {
      if (!seen.has(from) || !seen.has(to)) return;
      es.push({
        id: `${from}-${to}`,
        source: String(from),
        target: String(to),
        markerEnd: { type: MarkerType.ArrowClosed },
        label: mentions > 3 ? `${mentions}×` : undefined,
        style: { strokeWidth: Math.min(1 + mentions / 2, 4) },
      });
    };
    for (const parent of parents) link(parent.study_id, detail.id, parent.mention_count);
    for (const ancestor of [...hop1, ...hop2]) for (const via of ancestor.via) link(ancestor.study_id, via);
    for (const sibling of siblings) for (const via of sibling.via) link(via, sibling.study_id);
    return { nodes: ns, edges: es, byId: seen };
  }, [detail]);

  if (detail.state !== "paper") {
    return <p className="research-muted">A Lead has no Lineage of its own. Upload its PDF to trace it.</p>;
  }
  const chosen = picked === null ? null : byId.get(picked);

  return (
    <div className="research-lineage">
      <div className="research-lineage-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          colorMode={colorMode}
          fitView
          nodesConnectable={false}
          nodesDraggable={false}
          onNodeClick={(_, node) => setPicked(Number(node.id))}
          onNodeDoubleClick={(_, node) => {
            setPicked(null);
            onOpen(Number(node.id));
          }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <p className="research-muted research-lineage-hint">
        Click a Study to see it · double-click to re-centre the Lineage on it · dashed = Lead
      </p>
      {chosen && (
        <div className="research-callout">
          <span>
            <strong>{chosen.title}</strong> {chosen.year ? `(${chosen.year})` : ""} · {chosen.role}
          </span>
          <button type="button" className="nav-btn" onClick={() => onOpen(chosen.id)}>
            Open
          </button>
        </div>
      )}
    </div>
  );
}
