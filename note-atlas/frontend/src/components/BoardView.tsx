import { useCallback, useEffect, useRef, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type ColorMode,
  type NodeTypes,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { fetchNotes, patchNote } from "../api";
import { useCommandStack } from "../hooks/useCommandStack";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import type { NoteSummary } from "../types";
import { BoardNoteNode, type BoardNoteNode as BoardNoteNodeType } from "./nodes/BoardNoteNode";

const nodeTypes = {
  boardNote: BoardNoteNode,
} satisfies NodeTypes;

type Point = { x: number; y: number; z: number };

type BoardViewProps = {
  colorMode: ColorMode;
};

function toNode(note: NoteSummary): BoardNoteNodeType {
  return {
    id: String(note.id),
    type: "boardNote",
    position: { x: note.x, y: note.y },
    zIndex: note.z,
    data: {
      title: note.title,
      source: note.source,
      noteId: note.id,
      color: note.color,
      z: note.z,
    },
    draggable: true,
  };
}

function BoardCanvas({ colorMode }: BoardViewProps) {
  const reduceMotion = usePrefersReducedMotion();
  const { fitView } = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<BoardNoteNodeType>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const origins = useRef(new Map<string, Point>());
  const liftedZ = useRef(new Map<string, number>());
  const fitted = useRef(false);
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const { push, undo, redo, discard, canUndo, canRedo } = useCommandStack();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchNotes()
      .then((notes) => {
        if (!cancelled) {
          setNodes(notes.map(toNode));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load notes for the board.");
          setNodes([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setNodes]);

  useEffect(() => {
    if (loading || nodes.length === 0 || fitted.current) {
      return;
    }
    fitted.current = true;
    const frame = requestAnimationFrame(() => {
      void fitView({ padding: 0.25, duration: reduceMotion ? 0 : 200 });
    });
    return () => cancelAnimationFrame(frame);
  }, [fitView, loading, nodes.length, reduceMotion]);

  const applyPoint = useCallback(
    (noteId: number, point: Point) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === String(noteId)
            ? {
                ...node,
                position: { x: point.x, y: point.y },
                zIndex: point.z,
                data: { ...node.data, z: point.z },
              }
            : node,
        ),
      );
    },
    [setNodes],
  );

  const persistPoint = useCallback(async (noteId: number, point: Point, fallback: Point) => {
    applyPoint(noteId, point);
    try {
      await patchNote(noteId, { x: point.x, y: point.y, z: point.z });
    } catch {
      applyPoint(noteId, fallback);
      throw new Error("move failed");
    }
  }, [applyPoint]);

  const moveNote = useCallback(
    (noteId: number, from: Point, to: Point) => {
      if (Math.abs(from.x - to.x) < 0.5 && Math.abs(from.y - to.y) < 0.5) {
        return;
      }
      applyPoint(noteId, to);
      const command = {
        label: "move",
        undo: () => persistPoint(noteId, from, to),
        redo: () => persistPoint(noteId, to, from),
      };
      push(command);
      void patchNote(noteId, { x: to.x, y: to.y, z: to.z }).catch(() => {
        applyPoint(noteId, from);
        discard(command);
      });
    },
    [applyPoint, discard, persistPoint, push],
  );

  const onNodeDragStart: OnNodeDrag<BoardNoteNodeType> = useCallback(
    (_event, node) => {
      origins.current.set(node.id, {
        x: node.position.x,
        y: node.position.y,
        z: node.data.z,
      });
      setNodes((currentNodes) => {
        const maxZ = Math.max(0, ...currentNodes.map((item) => item.data.z));
        const nextZ = maxZ + 1;
        liftedZ.current.set(node.id, nextZ);
        return currentNodes.map((item) =>
          item.id === node.id
            ? {
                ...item,
                zIndex: nextZ,
                data: { ...item.data, z: nextZ },
              }
            : item,
        );
      });
    },
    [setNodes],
  );

  const onNodeDragStop: OnNodeDrag<BoardNoteNodeType> = useCallback(
    (_event, node) => {
      const from = origins.current.get(node.id);
      origins.current.delete(node.id);
      if (!from) {
        return;
      }
      const to: Point = {
        x: node.position.x,
        y: node.position.y,
        z: liftedZ.current.get(node.id) ?? node.data.z,
      };
      liftedZ.current.delete(node.id);
      const moved =
        Math.abs(from.x - to.x) >= 0.5 || Math.abs(from.y - to.y) >= 0.5;
      if (!moved) {
        void patchNote(node.data.noteId, { z: to.z }).catch(() => {
          applyPoint(node.data.noteId, from);
        });
        return;
      }
      moveNote(node.data.noteId, from, to);
    },
    [applyPoint, moveNote],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      const meta = event.metaKey || event.ctrlKey;
      if (!meta || event.key.toLowerCase() !== "z") {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      event.preventDefault();
      if (event.shiftKey) {
        void redo();
      } else {
        void undo();
      }
    }
    function onNudge(event: KeyboardEvent): void {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      const step = event.shiftKey ? 80 : 24;
      const selected = nodesRef.current.find((node) => node.selected);
      if (!selected) {
        return;
      }
      let dx = 0;
      let dy = 0;
      if (event.key === "ArrowUp") {
        dy = -step;
      } else if (event.key === "ArrowDown") {
        dy = step;
      } else if (event.key === "ArrowLeft") {
        dx = -step;
      } else if (event.key === "ArrowRight") {
        dx = step;
      } else {
        return;
      }
      event.preventDefault();
      const from = {
        x: selected.position.x,
        y: selected.position.y,
        z: selected.data.z,
      };
      moveNote(selected.data.noteId, from, { x: from.x + dx, y: from.y + dy, z: from.z });
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("keydown", onNudge);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keydown", onNudge);
    };
  }, [moveNote, redo, undo]);

  return (
    <>
      <div className="board-toolbar">
        <p className="repo-count">{loading ? "Loading board…" : `${nodes.length} notes`}</p>
        <div className="board-toolbar-actions">
          <button type="button" className="btn btn-ghost" disabled={!canUndo} onClick={() => void undo()}>
            Undo
          </button>
          <button type="button" className="btn btn-ghost" disabled={!canRedo} onClick={() => void redo()}>
            Redo
          </button>
        </div>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="board-canvas" role="application" aria-label="Board canvas">
        <ReactFlow
          nodes={nodes}
          onNodesChange={onNodesChange}
          nodeTypes={nodeTypes}
          onNodeDragStart={onNodeDragStart}
          onNodeDragStop={onNodeDragStop}
          minZoom={0.2}
          maxZoom={1.8}
          defaultViewport={{ x: 0, y: 0, zoom: 1 }}
          nodesDraggable
          nodeDragThreshold={0}
          nodesConnectable={false}
          elementsSelectable
          panOnDrag
          panOnScroll
          zoomOnScroll={!reduceMotion}
          zoomOnPinch
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          proOptions={{ hideAttribution: true }}
          colorMode={colorMode}
          onlyRenderVisibleElements
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
        {!loading && nodes.length === 0 ? (
          <p className="board-placeholder board-placeholder-overlay">
            No notes yet. Capture one, then return here.
          </p>
        ) : null}
      </div>
    </>
  );
}

export function BoardView({ colorMode }: BoardViewProps) {
  return (
    <section className="board-view" aria-label="Board">
      <ReactFlowProvider>
        <BoardCanvas colorMode={colorMode} />
      </ReactFlowProvider>
    </section>
  );
}
