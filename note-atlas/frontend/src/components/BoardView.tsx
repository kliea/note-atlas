import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  Background,
  ConnectionMode,
  Controls,
  Position,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type ColorMode,
  type Connection as RFConnection,
  type EdgeTypes,
  type IsValidConnection,
  type NodeTypes,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  createConnection,
  createNote,
  deleteConnection,
  deleteNote,
  downloadNoteExport,
  fetchConnections,
  fetchNote,
  fetchNotes,
  fetchSuggestions,
  importNoteFile,
  patchNote,
  streamAsk,
} from "../api";
import { useCommandStack } from "../hooks/useCommandStack";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { joinNoteText, splitNoteText } from "../noteText";
import type { Citation, Connection, LinkSuggestion, NoteCreate, NoteDetail } from "../types";
import { BoardAskBar } from "./BoardAskBar";
import { BoardShortcuts } from "./BoardShortcuts";
import {
  BoardConnectionLine,
  BoardGhostEdge,
  BoardStringEdge,
  type BoardGhostEdge as BoardGhostEdgeType,
  type BoardStringEdge as BoardStringEdgeType,
} from "./edges/BoardStringEdge";
import {
  BoardSessionContext,
  BoardNoteNode,
  type BoardNoteNode as BoardNoteNodeType,
  type BoardSession,
} from "./nodes/BoardNoteNode";

const nodeTypes = {
  boardNote: BoardNoteNode,
} satisfies NodeTypes;

const edgeTypes = {
  boardString: BoardStringEdge,
  boardGhost: BoardGhostEdge,
} satisfies EdgeTypes;

type Point = { x: number; y: number; z: number };

type AskSession = {
  origin: { x: number; y: number };
  noteIds: number[];
};

const NOTE_CARD_WIDTH = 240;
const NOTE_CARD_HEIGHT = 120;
const SNAP = 24;

function snapCoord(value: number): number {
  return Math.round(value / SNAP) * SNAP;
}

type BoardViewProps = {
  colorMode: ColorMode;
};

function toNode(note: NoteDetail, editing = false): BoardNoteNodeType {
  return {
    id: String(note.id),
    type: "boardNote",
    position: { x: note.x, y: note.y },
    zIndex: note.z,
    data: {
      title: note.title,
      source: note.source,
      rawText: note.raw_text,
      noteId: note.id,
      color: note.color,
      z: note.z,
      text: joinNoteText(note.title, note.raw_text),
      editing,
      extractStatus: note.extract_status ?? "idle",
      topics: note.topics ?? [],
    },
    draggable: !editing,
  };
}

function scopedNoteIds(nodes: BoardNoteNodeType[]): number[] {
  return nodes
    .filter(
      (node) => node.selected && node.data.noteId > 0 && node.data.source !== "ask",
    )
    .map((node) => node.data.noteId);
}

function selectionOrigin(selected: BoardNoteNodeType[]): { x: number; y: number } {
  const left = Math.min(...selected.map((node) => node.position.x));
  const right = Math.max(...selected.map((node) => node.position.x + NOTE_CARD_WIDTH));
  const bottom = Math.max(...selected.map((node) => node.position.y + NOTE_CARD_HEIGHT));
  return { x: (left + right) / 2 - NOTE_CARD_WIDTH / 2, y: bottom + 28 };
}

function makeAskNode(
  noteId: number,
  question: string,
  origin: { x: number; y: number },
  z: number,
  answer = "",
): BoardNoteNodeType {
  return {
    id: String(noteId),
    type: "boardNote",
    position: origin,
    zIndex: z,
    data: {
      title: question,
      source: "ask",
      rawText: answer,
      noteId,
      color: null,
      z,
      text: joinNoteText(question, answer),
      editing: false,
      extractStatus: "idle",
      topics: [],
    },
    draggable: noteId > 0,
  };
}

function closestSide(
  from: { x: number; y: number },
  to: { x: number; y: number },
): Position {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) > Math.abs(dy)) {
    return dx >= 0 ? Position.Right : Position.Left;
  }
  return dy >= 0 ? Position.Bottom : Position.Top;
}

function toEdge(
  conn: Connection,
  nodeList: BoardNoteNodeType[],
  handles?: { sourceHandle?: string | null; targetHandle?: string | null },
): BoardStringEdgeType {
  const source = nodeList.find((node) => node.data.noteId === conn.from_note_id);
  const target = nodeList.find((node) => node.data.noteId === conn.to_note_id);
  const sourceHandle =
    handles?.sourceHandle ??
    (source && target ? `out-${closestSide(source.position, target.position)}` : "out-right");
  const targetHandle =
    handles?.targetHandle ??
    (source && target ? closestSide(target.position, source.position) : Position.Left);
  return {
    id: `conn-${conn.id}`,
    type: "boardString",
    source: String(conn.from_note_id),
    target: String(conn.to_note_id),
    sourceHandle,
    targetHandle,
    data: { connectionId: conn.id },
    interactionWidth: 24,
  };
}

function pairKey(left: number, right: number): string {
  return left < right ? `${left}:${right}` : `${right}:${left}`;
}

function toGhost(
  fromId: number,
  suggestion: LinkSuggestion,
  nodeList: BoardNoteNodeType[],
): BoardGhostEdgeType {
  const source = nodeList.find((node) => node.data.noteId === fromId);
  const target = nodeList.find((node) => node.data.noteId === suggestion.note_id);
  const sourceHandle =
    source && target ? `out-${closestSide(source.position, target.position)}` : "out-right";
  const targetHandle =
    source && target ? closestSide(target.position, source.position) : Position.Left;
  return {
    id: `ghost-${pairKey(fromId, suggestion.note_id)}`,
    type: "boardGhost",
    source: String(fromId),
    target: String(suggestion.note_id),
    sourceHandle,
    targetHandle,
    selectable: false,
    focusable: false,
    data: {
      fromId,
      toId: suggestion.note_id,
      score: suggestion.score,
      reason: suggestion.reason,
      title: suggestion.title,
    },
    interactionWidth: 24,
  };
}

function linkedIdsFor(
  nodes: BoardNoteNodeType[],
  edges: BoardStringEdgeType[],
): Set<string> | null {
  const selected = new Set(
    nodes.filter((node) => node.selected && node.data.noteId > 0).map((node) => node.id),
  );
  if (selected.size === 0) {
    return null;
  }
  const linked = new Set(selected);
  for (const edge of edges) {
    if (selected.has(edge.source) || selected.has(edge.target)) {
      linked.add(edge.source);
      linked.add(edge.target);
    }
  }
  return linked;
}

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable)
  );
}

function BoardCanvas({ colorMode }: BoardViewProps) {
  const reduceMotion = usePrefersReducedMotion();
  const { fitView, screenToFlowPosition } = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<BoardNoteNodeType>([]);
  const [edges, setEdges] = useEdgesState<BoardStringEdgeType>([]);
  const [ghosts, setGhosts] = useState<BoardGhostEdgeType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const origins = useRef(new Map<string, Point>());
  const liftedZ = useRef(new Map<string, number>());
  const fitted = useRef(false);
  const draftSeq = useRef(-1);
  const lastPaneTap = useRef(0);
  const lastPointer = useRef<{ x: number; y: number } | null>(null);
  const committing = useRef(new Set<string>());
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;
  const dismissedPairs = useRef(new Set<string>());
  const suggestedFor = useRef(new Set<number>());
  const askingRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [askSession, setAskSession] = useState<AskSession | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const { push, undo, redo, discard, canUndo, canRedo } = useCommandStack();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all([
      fetchNotes().then((listed) => Promise.all(listed.map((note) => fetchNote(note.id)))),
      fetchConnections(),
    ])
      .then(([details, connections]) => {
        if (cancelled) {
          return;
        }
        const nextNodes = details.map((note) => toNode(note));
        setNodes(nextNodes);
        const ids = new Set(nextNodes.map((node) => node.id));
        setEdges(
          connections
            .filter(
              (conn) =>
                ids.has(String(conn.from_note_id)) && ids.has(String(conn.to_note_id)),
            )
            .map((conn) => toEdge(conn, nextNodes)),
        );
        setGhosts([]);
        dismissedPairs.current.clear();
        suggestedFor.current.clear();
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load notes for the board.");
          setNodes([]);
          setEdges([]);
          setGhosts([]);
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
  }, [setEdges, setNodes]);

  const thinkingKey = nodes
    .filter(
      (node) =>
        node.data.noteId > 0 &&
        (node.data.extractStatus === "pending" || node.data.extractStatus === "running"),
    )
    .map((node) => node.data.noteId)
    .sort((left, right) => left - right)
    .join(",");

  useEffect(() => {
    if (loading || fitted.current) {
      return;
    }
    fitted.current = true;
    if (nodes.length === 0) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      void fitView({ padding: 0.22, duration: reduceMotion ? 0 : 280, maxZoom: 1.15 });
    });
    return () => cancelAnimationFrame(frame);
  }, [fitView, loading, nodes.length, reduceMotion]);

  const applyPoint = useCallback(
    (noteId: number, point: Point) => {
      setNodes((current) =>
        current.map((node) =>
          node.data.noteId === noteId
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

  const persistPoint = useCallback(
    async (noteId: number, point: Point, fallback: Point) => {
      applyPoint(noteId, point);
      try {
        await patchNote(noteId, { x: point.x, y: point.y, z: point.z });
      } catch {
        applyPoint(noteId, fallback);
        throw new Error("move failed");
      }
    },
    [applyPoint],
  );

  const moveNote = useCallback(
    (noteId: number, from: Point, to: Point) => {
      if (noteId < 0) {
        applyPoint(noteId, to);
        return;
      }
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
      if (node.data.editing) {
        return;
      }
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
        x: snapCoord(node.position.x),
        y: snapCoord(node.position.y),
        z: liftedZ.current.get(node.id) ?? node.data.z,
      };
      liftedZ.current.delete(node.id);
      if (node.data.noteId < 0) {
        return;
      }
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

  const removeByNoteId = useCallback(
    (noteId: number, nodeId?: string) => {
      const dropIds = new Set([String(noteId), nodeId].filter(Boolean) as string[]);
      setNodes((current) =>
        current.filter(
          (node) => node.data.noteId !== noteId && node.id !== nodeId,
        ),
      );
      setEdges((current) =>
        current.filter((edge) => !dropIds.has(edge.source) && !dropIds.has(edge.target)),
      );
      setGhosts((current) =>
        current.filter((edge) => !dropIds.has(edge.source) && !dropIds.has(edge.target)),
      );
    },
    [setEdges, setNodes],
  );

  const addOrReplace = useCallback(
    (note: NoteDetail, editing = false) => {
      const next = toNode(note, editing);
      setNodes((current) => {
        const without = current.filter(
          (node) => node.id !== next.id && node.data.noteId !== note.id,
        );
        return [...without, next];
      });
    },
    [setNodes],
  );

  const pushCreateCommand = useCallback(
    (created: NoteDetail, payload: NoteCreate) => {
      let currentId = created.id;
      push({
        label: "create",
        undo: async () => {
          await deleteNote(currentId);
          removeByNoteId(currentId);
        },
        redo: async () => {
          const again = await createNote(payload);
          currentId = again.id;
          addOrReplace(again);
        },
      });
    },
    [addOrReplace, push, removeByNoteId],
  );

  const pairLinked = useCallback((sourceId: string, targetId: string): boolean => {
    return edgesRef.current.some(
      (edge) =>
        (edge.source === sourceId && edge.target === targetId) ||
        (edge.source === targetId && edge.target === sourceId),
    );
  }, []);

  const dropGhost = useCallback((fromId: number, toId: number) => {
    const key = pairKey(fromId, toId);
    setGhosts((current) =>
      current.filter((edge) => pairKey(edge.data?.fromId ?? 0, edge.data?.toId ?? 0) !== key),
    );
  }, []);

  const persistLink = useCallback(
    (fromId: number, toId: number, handles?: { sourceHandle?: string | null; targetHandle?: string | null }) => {
      const source = String(fromId);
      const target = String(toId);
      if (fromId < 1 || toId < 1 || fromId === toId || pairLinked(source, target)) {
        return;
      }
      const payload = { from_note_id: fromId, to_note_id: toId };
      const pendingId = `pending-${fromId}-${toId}`;
      const pending = toEdge(
        { id: -1, from_note_id: fromId, to_note_id: toId, kind: "link", created_at: "" },
        nodesRef.current,
        handles,
      );
      setEdges((current) => [...current, { ...pending, id: pendingId }]);
      dropGhost(fromId, toId);
      void createConnection(payload)
        .then((created) => {
          setEdges((current) =>
            current.map((edge) =>
              edge.id === pendingId ? toEdge(created, nodesRef.current, handles) : edge,
            ),
          );
          let currentId = created.id;
          push({
            label: "link",
            undo: async () => {
              await deleteConnection(currentId);
              setEdges((current) =>
                current.filter((edge) => edge.data?.connectionId !== currentId),
              );
            },
            redo: async () => {
              const again = await createConnection(payload);
              currentId = again.id;
              setEdges((current) => {
                const without = current.filter(
                  (edge) =>
                    !(
                      (edge.source === source && edge.target === target) ||
                      (edge.source === target && edge.target === source)
                    ),
                );
                return [...without, toEdge(again, nodesRef.current)];
              });
            },
          });
        })
        .catch(() => {
          setEdges((current) => current.filter((edge) => edge.id !== pendingId));
          setError("Could not connect those notes.");
        });
    },
    [dropGhost, pairLinked, push, setEdges],
  );

  const loadSuggestions = useCallback(
    (noteId: number) => {
      void fetchSuggestions(noteId)
        .then((items) => {
          setGhosts((current) => {
            const keep = current.filter(
              (edge) => edge.data?.fromId !== noteId && edge.data?.toId !== noteId,
            );
            const seen = new Set(
              keep.map((edge) => pairKey(edge.data?.fromId ?? 0, edge.data?.toId ?? 0)),
            );
            const next: BoardGhostEdgeType[] = [];
            for (const item of items) {
              const key = pairKey(noteId, item.note_id);
              if (dismissedPairs.current.has(key) || seen.has(key)) {
                continue;
              }
              if (pairLinked(String(noteId), String(item.note_id))) {
                continue;
              }
              seen.add(key);
              next.push(toGhost(noteId, item, nodesRef.current));
            }
            return [...keep, ...next];
          });
        })
        .catch(() => {
          suggestedFor.current.delete(noteId);
        });
    },
    [pairLinked],
  );

  const mergeExtracted = useCallback(
    (note: NoteDetail) => {
      if (note.extract_status === "pending" || note.extract_status === "running") {
        suggestedFor.current.delete(note.id);
      }
      setNodes((current) =>
        current.map((node) => {
          if (node.data.noteId !== note.id) {
            return node;
          }
          if (node.data.editing) {
            return {
              ...node,
              data: {
                ...node.data,
                extractStatus: note.extract_status,
                topics: note.topics,
              },
            };
          }
          return {
            ...node,
            data: {
              ...node.data,
              title: note.title,
              source: note.source,
              rawText: note.raw_text,
              text: joinNoteText(note.title, note.raw_text),
              extractStatus: note.extract_status,
              topics: note.topics,
            },
          };
        }),
      );
    },
    [setNodes],
  );

  const acceptSuggestion = useCallback(
    (fromId: number, toId: number) => {
      persistLink(fromId, toId);
    },
    [persistLink],
  );

  const dismissSuggestion = useCallback(
    (fromId: number, toId: number) => {
      dismissedPairs.current.add(pairKey(fromId, toId));
      dropGhost(fromId, toId);
    },
    [dropGhost],
  );

  useEffect(() => {
    if (!thinkingKey) {
      return;
    }
    const ids = thinkingKey.split(",").map(Number);
    let cancelled = false;
    const tick = () => {
      void Promise.all(ids.map((id) => fetchNote(id)))
        .then((details) => {
          if (cancelled) {
            return;
          }
          for (const detail of details) {
            mergeExtracted(detail);
          }
        })
        .catch(() => {
          /* keep shimmering until the next tick */
        });
    };
    tick();
    const timer = window.setInterval(tick, 1200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [mergeExtracted, thinkingKey]);

  useEffect(() => {
    for (const node of nodes) {
      if (node.data.noteId < 1) {
        continue;
      }
      const ready =
        node.data.extractStatus === "done" ||
        (node.data.extractStatus !== "pending" &&
          node.data.extractStatus !== "running" &&
          node.data.topics.length > 0);
      if (!ready || suggestedFor.current.has(node.data.noteId)) {
        continue;
      }
      suggestedFor.current.add(node.data.noteId);
      loadSuggestions(node.data.noteId);
    }
  }, [loadSuggestions, nodes]);

  const cutConnection = useCallback(
    (connectionId: number) => {
      const edge = edgesRef.current.find((item) => item.data?.connectionId === connectionId);
      if (!edge || connectionId < 1) {
        return;
      }
      const payload = {
        from_note_id: Number(edge.source),
        to_note_id: Number(edge.target),
      };
      void deleteConnection(connectionId)
        .then(() => {
          setEdges((current) =>
            current.filter((item) => item.data?.connectionId !== connectionId),
          );
          let currentId = connectionId;
          push({
            label: "cut",
            undo: async () => {
              const restored = await createConnection(payload);
              currentId = restored.id;
              setEdges((current) => [...current, toEdge(restored, nodesRef.current)]);
            },
            redo: async () => {
              await deleteConnection(currentId);
              setEdges((current) =>
                current.filter((item) => item.data?.connectionId !== currentId),
              );
            },
          });
        })
        .catch(() => {
          setError("Could not cut that connection.");
        });
    },
    [push, setEdges],
  );

  const onConnect = useCallback(
    (connection: RFConnection) => {
      const fromId = Number(connection.source);
      const toId = Number(connection.target);
      persistLink(fromId, toId, {
        sourceHandle: connection.sourceHandle,
        targetHandle: connection.targetHandle,
      });
    },
    [persistLink],
  );

  const isValidConnection = useCallback<IsValidConnection>(
    (connection) => {
      const source = connection.source;
      const target = connection.target;
      if (!source || !target || source === target) {
        return false;
      }
      const fromId = Number(source);
      const toId = Number(target);
      if (fromId < 1 || toId < 1) {
        return false;
      }
      return !pairLinked(source, target);
    },
    [pairLinked],
  );

  const updateText = useCallback(
    (nodeId: string, text: string) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, text } } : node,
        ),
      );
    },
    [setNodes],
  );

  const stopEditing = useCallback(
    (nodeId: string, extra?: Partial<BoardNoteNodeType["data"]>) => {
      setNodes((current) =>
        current.map((item) =>
          item.id === nodeId
            ? {
                ...item,
                data: { ...item.data, ...extra, editing: false },
                draggable: true,
              }
            : item,
        ),
      );
    },
    [setNodes],
  );

  const commitEdit = useCallback(
    (nodeId: string, text: string) => {
      if (committing.current.has(nodeId)) {
        return;
      }
      const node = nodesRef.current.find((item) => item.id === nodeId);
      if (!node || !node.data.editing) {
        return;
      }
      const parsed = splitNoteText(text);
      if (!parsed && node.data.noteId < 0) {
        window.setTimeout(() => {
          const current = nodesRef.current.find((item) => item.id === nodeId);
          if (!current || current.data.noteId >= 0 || !current.data.editing) {
            return;
          }
          if (splitNoteText(current.data.text)) {
            return;
          }
          if (
            document.activeElement instanceof HTMLTextAreaElement &&
            document.activeElement.classList.contains("board-note-editor")
          ) {
            return;
          }
          removeByNoteId(current.data.noteId, nodeId);
        }, 50);
        return;
      }
      committing.current.add(nodeId);
      const finish = () => {
        committing.current.delete(nodeId);
      };

      if (!parsed) {
        const snapshot: NoteCreate = {
          title: node.data.title,
          source: node.data.source,
          raw_text: node.data.rawText || node.data.title,
          x: node.position.x,
          y: node.position.y,
        };
        let currentId = node.data.noteId;
        void deleteNote(currentId)
          .then(() => {
            removeByNoteId(currentId, nodeId);
            push({
              label: "delete",
              undo: async () => {
                const restored = await createNote(snapshot);
                currentId = restored.id;
                addOrReplace(restored);
              },
              redo: async () => {
                await deleteNote(currentId);
                removeByNoteId(currentId);
              },
            });
          })
          .catch(() => {
            setNodes((current) =>
              current.map((item) =>
                item.id === nodeId
                  ? { ...item, data: { ...item.data, editing: true }, draggable: false }
                  : item,
              ),
            );
          })
          .finally(finish);
        return;
      }

      stopEditing(nodeId, { title: parsed.title, text });

      if (node.data.noteId < 0) {
        const payload: NoteCreate = {
          title: parsed.title,
          source: "",
          raw_text: parsed.raw_text,
          x: node.position.x,
          y: node.position.y,
        };
        void createNote(payload)
          .then((created) => {
            removeByNoteId(node.data.noteId, nodeId);
            addOrReplace(created);
            pushCreateCommand(created, {
              ...payload,
              x: created.x,
              y: created.y,
            });
          })
          .catch(() => {
            setError("Could not save that note.");
            removeByNoteId(node.data.noteId, nodeId);
          })
          .finally(finish);
        return;
      }

      const prevTitle = node.data.title;
      const prevRaw = node.data.rawText || prevTitle;
      if (prevTitle === parsed.title && prevRaw === parsed.raw_text) {
        finish();
        return;
      }
      const noteId = node.data.noteId;
      void patchNote(noteId, { title: parsed.title, raw_text: parsed.raw_text })
        .then((updated) => {
          addOrReplace(updated);
          push({
            label: "edit",
            undo: async () => {
              const restored = await patchNote(noteId, {
                title: prevTitle,
                raw_text: prevRaw,
              });
              addOrReplace(restored);
            },
            redo: async () => {
              const again = await patchNote(noteId, {
                title: parsed.title,
                raw_text: parsed.raw_text,
              });
              addOrReplace(again);
            },
          });
        })
        .catch(() => {
          setError("Could not update that note.");
          stopEditing(nodeId, { text: node.data.text, title: prevTitle });
        })
        .finally(finish);
    },
    [addOrReplace, push, pushCreateCommand, removeByNoteId, setNodes, stopEditing],
  );

  const startEdit = useCallback(
    (nodeId: string) => {
      const open = nodesRef.current.find((item) => item.data.editing && item.id !== nodeId);
      if (open) {
        commitEdit(open.id, open.data.text);
      }
      setNodes((current) =>
        current.map((item) =>
          item.id === nodeId
            ? { ...item, data: { ...item.data, editing: true }, draggable: false }
            : item,
        ),
      );
    },
    [commitEdit, setNodes],
  );

  const spawnDraft = useCallback(
    (position: { x: number; y: number }) => {
      const open = nodesRef.current.find((item) => item.data.editing);
      if (open) {
        commitEdit(open.id, open.data.text);
      }
      const noteId = draftSeq.current;
      draftSeq.current -= 1;
      const id = `draft-${noteId}`;
      const maxZ = Math.max(0, ...nodesRef.current.map((item) => item.data.z));
      setNodes((current) => [
        ...current.map((item) =>
          item.data.editing
            ? { ...item, data: { ...item.data, editing: false }, draggable: true }
            : item,
        ),
        {
          id,
          type: "boardNote" as const,
          position,
          zIndex: maxZ + 1,
          data: {
            title: "",
            source: "",
            rawText: "",
            noteId,
            color: null,
            z: maxZ + 1,
            text: "",
            editing: true,
            extractStatus: "idle",
            topics: [],
          },
          draggable: false,
        },
      ]);
    },
    [commitEdit, setNodes],
  );

  const persistPasted = useCallback(
    (position: { x: number; y: number }, text: string) => {
      const parsed = splitNoteText(text);
      if (!parsed) {
        return;
      }
      const payload: NoteCreate = {
        title: parsed.title,
        source: "",
        raw_text: parsed.raw_text,
        x: position.x,
        y: position.y,
      };
      void createNote(payload)
        .then((created) => {
          addOrReplace(created);
          pushCreateCommand(created, { ...payload, x: created.x, y: created.y });
        })
        .catch(() => {
          setError("Could not save the pasted note.");
        });
    },
    [addOrReplace, pushCreateCommand],
  );

  const runBoardAsk = useCallback(
    (question: string, session: AskSession) => {
      const trimmed = question.trim();
      if (!trimmed || askingRef.current) {
        return;
      }
      setAskSession(null);
      askingRef.current = true;
      const draftId = draftSeq.current;
      draftSeq.current -= 1;
      const maxZ = Math.max(0, ...nodesRef.current.map((node) => node.data.z)) + 1;
      setNodes((current) => [...current, makeAskNode(draftId, trimmed, session.origin, maxZ)]);
      let answer = "";
      let citations: Citation[] = [];
      void streamAsk(
        trimmed,
        {
          onMeta: (meta) => {
            citations = meta.citations;
          },
          onToken: (piece) => {
            answer += piece;
            setNodes((current) =>
              current.map((node) =>
                node.data.noteId === draftId
                  ? {
                      ...node,
                      data: {
                        ...node.data,
                        rawText: answer,
                        text: joinNoteText(trimmed, answer),
                      },
                    }
                  : node,
              ),
            );
          },
          onError: (detail) => {
            setError(detail);
          },
        },
        undefined,
        session.noteIds,
      )
        .then(async () => {
          const body = answer.trim();
          if (!body) {
            removeByNoteId(draftId);
            return;
          }
          const payload: NoteCreate = {
            title: trimmed.slice(0, 120),
            source: "ask",
            raw_text: body,
            x: session.origin.x,
            y: session.origin.y,
          };
          const created = await createNote(payload);
          const pinned = await patchNote(created.id, { pinned: true, z: maxZ }).catch(
            () => created,
          );
          removeByNoteId(draftId);
          addOrReplace(pinned);
          const cited = [
            ...new Set(citations.map((item) => item.note_id).filter((id) => id !== pinned.id)),
          ];
          for (const id of cited) {
            persistLink(pinned.id, id);
          }
          let currentId = pinned.id;
          push({
            label: "ask",
            undo: async () => {
              await deleteNote(currentId);
              removeByNoteId(currentId);
            },
            redo: async () => {
              const again = await createNote(payload);
              currentId = again.id;
              const restored = await patchNote(currentId, { pinned: true, z: maxZ }).catch(
                () => again,
              );
              addOrReplace(restored);
              for (const id of cited) {
                persistLink(currentId, id);
              }
            },
          });
        })
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Ask failed.");
        })
        .finally(() => {
          askingRef.current = false;
        });
    },
    [addOrReplace, persistLink, push, removeByNoteId, setNodes],
  );

  const session = useMemo<BoardSession>(
    () => ({
      startEdit,
      updateText,
      commitEdit,
      cutConnection,
      acceptSuggestion,
      dismissSuggestion,
    }),
    [acceptSuggestion, commitEdit, cutConnection, dismissSuggestion, startEdit, updateText],
  );

  const linkedIds = useMemo(() => linkedIdsFor(nodes, edges), [edges, nodes]);
  const displayNodes = useMemo(
    () =>
      linkedIds
        ? nodes.map((node) => ({
            ...node,
            className: linkedIds.has(node.id) ? "board-linked" : "board-dimmed",
          }))
        : nodes.map((node) => ({ ...node, className: undefined })),
    [linkedIds, nodes],
  );
  const displayEdges = useMemo(() => {
    const real = linkedIds
      ? edges.map((edge) => ({
          ...edge,
          className:
            linkedIds.has(edge.source) &&
            linkedIds.has(edge.target) &&
            (nodes.some((node) => node.selected && node.id === edge.source) ||
              nodes.some((node) => node.selected && node.id === edge.target))
              ? "board-linked"
              : "board-dimmed",
        }))
      : edges.map((edge) => ({ ...edge, className: undefined }));
    const suggested = linkedIds
      ? ghosts.map((edge) => ({
          ...edge,
          className:
            linkedIds.has(edge.source) || linkedIds.has(edge.target)
              ? "board-linked"
              : "board-dimmed",
        }))
      : ghosts;
    return [...real, ...suggested];
  }, [edges, ghosts, linkedIds, nodes]);

  const onPaneClick = useCallback(
    (event: MouseEvent) => {
      const now = Date.now();
      const isDouble = now - lastPaneTap.current < 350;
      lastPaneTap.current = isDouble ? 0 : now;
      if (!isDouble) {
        return;
      }
      spawnDraft(screenToFlowPosition({ x: event.clientX, y: event.clientY }));
    },
    [screenToFlowPosition, spawnDraft],
  );

  const onSelectionEnd = useCallback(() => {
    if (askingRef.current) {
      return;
    }
    const selected = nodesRef.current.filter(
      (node) => node.selected && node.data.noteId > 0 && node.data.source !== "ask",
    );
    if (selected.length === 0) {
      return;
    }
    setAskSession({
      origin: selectionOrigin(selected),
      noteIds: scopedNoteIds(nodesRef.current),
    });
  }, []);

  const spawnAtViewCenter = useCallback(() => {
    const canvas = document.querySelector(".board-canvas");
    if (!(canvas instanceof HTMLElement)) {
      spawnDraft({ x: 240, y: 180 });
      return;
    }
    const box = canvas.getBoundingClientRect();
    spawnDraft(
      screenToFlowPosition({
        x: box.left + box.width / 2,
        y: box.top + box.height / 2,
      }),
    );
  }, [screenToFlowPosition, spawnDraft]);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      const meta = event.metaKey || event.ctrlKey;
      if (!meta || event.key.toLowerCase() !== "z") {
        return;
      }
      if (isTypingTarget(event.target)) {
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
      if (isTypingTarget(event.target)) {
        return;
      }
      const step = event.shiftKey ? SNAP * 4 : SNAP;
      const selected = nodesRef.current.find((node) => node.selected && !node.data.editing);
      if (!selected || selected.data.noteId < 0) {
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
      moveNote(selected.data.noteId, from, {
        x: snapCoord(from.x + dx),
        y: snapCoord(from.y + dy),
        z: from.z,
      });
    }
    function onPaste(event: ClipboardEvent): void {
      if (isTypingTarget(event.target)) {
        return;
      }
      const text = event.clipboardData?.getData("text/plain") ?? "";
      if (!splitNoteText(text)) {
        return;
      }
      event.preventDefault();
      const canvas = document.querySelector(".board-canvas");
      let position = { x: 240, y: 180 };
      if (lastPointer.current) {
        position = screenToFlowPosition(lastPointer.current);
      } else if (canvas instanceof HTMLElement) {
        const box = canvas.getBoundingClientRect();
        position = screenToFlowPosition({
          x: box.left + box.width / 2,
          y: box.top + box.height / 2,
        });
      }
      persistPasted(position, text);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("keydown", onNudge);
    window.addEventListener("paste", onPaste);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keydown", onNudge);
      window.removeEventListener("paste", onPaste);
    };
  }, [moveNote, persistPasted, redo, screenToFlowPosition, undo]);

  useEffect(() => {
    function openAskPrompt(): void {
      if (askingRef.current) {
        return;
      }
      const selected = nodesRef.current.filter(
        (node) => node.selected && node.data.noteId > 0 && node.data.source !== "ask",
      );
      let origin = { x: 240, y: 180 };
      if (selected.length > 0) {
        origin = selectionOrigin(selected);
      } else if (lastPointer.current) {
        origin = screenToFlowPosition(lastPointer.current);
      }
      setAskSession({
        origin,
        noteIds: scopedNoteIds(nodesRef.current),
      });
    }

    function onBoardKey(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        if (shortcutsOpen) {
          event.preventDefault();
          setShortcutsOpen(false);
          return;
        }
        if (askSession && !askingRef.current && !isTypingTarget(event.target)) {
          event.preventDefault();
          setAskSession(null);
        }
        return;
      }
      if (isTypingTarget(event.target)) {
        return;
      }
      if (event.key === "?") {
        event.preventDefault();
        setShortcutsOpen((open) => !open);
        return;
      }
      if (shortcutsOpen) {
        return;
      }
      if (event.key === "/") {
        event.preventDefault();
        openAskPrompt();
        return;
      }
      if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        spawnAtViewCenter();
        return;
      }
      if (event.key === "Enter") {
        const selected = nodesRef.current.find(
          (node) => node.selected && !node.data.editing && node.data.noteId !== 0,
        );
        if (!selected) {
          return;
        }
        event.preventDefault();
        startEdit(selected.id);
        return;
      }
      if (event.key === "l" || event.key === "L") {
        const selected = nodesRef.current.filter(
          (node) => node.selected && node.data.noteId > 0,
        );
        event.preventDefault();
        if (selected.length !== 2) {
          setError("Select two notes, then press L to link them.");
          return;
        }
        persistLink(selected[0].data.noteId, selected[1].data.noteId);
        return;
      }
      if (event.key === "Backspace" || event.key === "Delete") {
        const selected = nodesRef.current.find(
          (node) => node.selected && node.data.noteId > 0 && !node.data.editing,
        );
        if (!selected) {
          return;
        }
        event.preventDefault();
        const snapshot: NoteCreate = {
          title: selected.data.title,
          source: selected.data.source,
          raw_text: selected.data.rawText || selected.data.title,
          x: selected.position.x,
          y: selected.position.y,
        };
        const noteId = selected.data.noteId;
        void deleteNote(noteId)
          .then(() => {
            removeByNoteId(noteId);
            let currentId = noteId;
            push({
              label: "delete",
              undo: async () => {
                const restored = await createNote(snapshot);
                currentId = restored.id;
                addOrReplace(restored);
              },
              redo: async () => {
                await deleteNote(currentId);
                removeByNoteId(currentId);
              },
            });
          })
          .catch(() => {
            setError("Could not delete that note.");
          });
      }
    }
    window.addEventListener("keydown", onBoardKey);
    return () => window.removeEventListener("keydown", onBoardKey);
  }, [
    addOrReplace,
    askSession,
    persistLink,
    push,
    removeByNoteId,
    screenToFlowPosition,
    shortcutsOpen,
    spawnAtViewCenter,
    startEdit,
  ]);

  return (
    <BoardSessionContext.Provider value={session}>
      <div className="board-toolbar">
        <p className="repo-count">
          {loading
            ? "Loading board…"
            : `${nodes.length} notes${
                edges.length === 0
                  ? ""
                  : edges.length === 1
                    ? " · 1 link"
                    : ` · ${edges.length} links`
              }`}
        </p>
        <p className="board-hint">N new · / ask · ? shortcuts</p>
        <div className="board-toolbar-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setShortcutsOpen(true)}
            aria-keyshortcuts="?"
          >
            Shortcuts
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => fileInputRef.current?.click()}
          >
            Import
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!nodes.some((node) => node.selected && node.data.noteId > 0)}
            onClick={() => {
              const selected = nodes.find((node) => node.selected && node.data.noteId > 0);
              if (!selected) {
                return;
              }
              void downloadNoteExport(selected.data.noteId, "json").catch(() => {
                setError("Export failed.");
              });
            }}
          >
            Export
          </button>
          <button type="button" className="btn btn-ghost" disabled={!canUndo} onClick={() => void undo()} aria-keyshortcuts="Control+Z Meta+Z">
            Undo
          </button>
          <button type="button" className="btn btn-ghost" disabled={!canRedo} onClick={() => void redo()} aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z">
            Redo
          </button>
        </div>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,.md,.markdown,application/json,text/markdown"
        hidden
        aria-label="Import a note file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) {
            return;
          }
          void importNoteFile(file)
            .then((imported) => {
              addOrReplace(imported);
            })
            .catch((err: unknown) => {
              setError(err instanceof Error ? err.message : "Import failed.");
            });
        }}
      />
      {error ? <p className="form-error">{error}</p> : null}
      <div
        className={linkedIds ? "board-canvas has-selection" : "board-canvas"}
        role="application"
        aria-label="Board canvas"
        aria-keyshortcuts="N / ? L Enter"
        tabIndex={0}
        onPointerMove={(event) => {
          lastPointer.current = { x: event.clientX, y: event.clientY };
        }}
        onDragOver={(event) => {
          event.preventDefault();
        }}
        onDrop={(event) => {
          event.preventDefault();
          const file = event.dataTransfer.files[0];
          if (!file) {
            return;
          }
          void importNoteFile(file)
            .then((imported) => {
              addOrReplace(imported);
            })
            .catch((err: unknown) => {
              setError(err instanceof Error ? err.message : "Import failed.");
            });
        }}
      >
        <ReactFlow
          nodes={displayNodes}
          edges={displayEdges}
          onNodesChange={onNodesChange}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeDragStart={onNodeDragStart}
          onNodeDragStop={onNodeDragStop}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          connectionMode={ConnectionMode.Loose}
          connectOnClick
          connectionLineComponent={BoardConnectionLine}
          onPaneClick={onPaneClick}
          onSelectionEnd={onSelectionEnd}
          selectionOnDrag={false}
          selectionMode={SelectionMode.Partial}
          selectionKeyCode="Shift"
          snapToGrid
          snapGrid={[SNAP, SNAP]}
          minZoom={0.2}
          maxZoom={1.8}
          defaultViewport={{ x: 0, y: 0, zoom: 1 }}
          nodesDraggable
          nodeDragThreshold={1}
          nodesConnectable
          nodesFocusable
          elementsSelectable
          edgesFocusable={false}
          panOnDrag
          panOnScroll
          autoPanOnNodeDrag={!reduceMotion}
          autoPanOnConnect={!reduceMotion}
          zoomOnScroll
          zoomOnPinch
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          proOptions={{ hideAttribution: true }}
          colorMode={colorMode}
        >
          <Background gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
        {askSession ? (
          <BoardAskBar
            origin={askSession.origin}
            noteIds={askSession.noteIds}
            onSubmit={(question) => runBoardAsk(question, askSession)}
            onClose={() => setAskSession(null)}
          />
        ) : null}
        {shortcutsOpen ? <BoardShortcuts onClose={() => setShortcutsOpen(false)} /> : null}
        <button
          type="button"
          className="board-pad"
          onMouseDown={(event) => event.preventDefault()}
          onClick={spawnAtViewCenter}
          aria-label="Tear off a new note"
        >
          New note
        </button>
        {!loading && nodes.length === 0 ? (
          <p className="board-placeholder board-placeholder-overlay">
            Double-click empty space or press N to write a note. Press ? for shortcuts.
          </p>
        ) : null}
      </div>
    </BoardSessionContext.Provider>
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
