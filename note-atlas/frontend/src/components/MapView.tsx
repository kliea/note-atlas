import { useEffect, useMemo, useState } from "react";
import {
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type ColorMode,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { fetchNote } from "../api";
import { buildAtlasGraph } from "../graph";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import type { NoteDetail, NoteSummary } from "../types";
import { NoteNode } from "./nodes/NoteNode";
import { TopicNode } from "./nodes/TopicNode";

const nodeTypes = {
  note: NoteNode,
  topic: TopicNode,
} satisfies NodeTypes;

type MapViewProps = {
  notes: NoteSummary[];
  selectedTopicId: number | null;
  colorMode: ColorMode;
  onSelectTopic: (topicId: number, noteId: number) => void;
  onSelectNote: (noteId: number) => void;
  onFocusCard: () => void;
};

export function MapView({
  notes,
  selectedTopicId,
  colorMode,
  onSelectTopic,
  onSelectNote,
  onFocusCard,
}: MapViewProps) {
  const [details, setDetails] = useState<NoteDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linkTags, setLinkTags] = useState(true);
  const reduceMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (notes.length === 0) {
      setDetails([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all(notes.map((note) => fetchNote(note.id)))
      .then((loaded) => {
        if (!cancelled) {
          setDetails([...loaded].sort((a, b) => a.id - b.id));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load notes for the map.");
          setDetails([]);
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
  }, [notes]);

  const { nodes, edges } = useMemo(
    () => buildAtlasGraph(details, selectedTopicId, linkTags),
    [details, selectedTopicId, linkTags],
  );
  const topicCount = details.reduce((sum, note) => sum + note.topics.length, 0);

  return (
    <section className="map-view">
      <div className="repo-toolbar">
        <p className="repo-count">
          {details.length} notes · {topicCount} topics
        </p>
        <label className="map-toggle">
          <input
            type="checkbox"
            checked={linkTags}
            onChange={(event) => setLinkTags(event.target.checked)}
          />
          Link shared tags
        </label>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {loading ? <p className="topics-status">Loading map…</p> : null}
      {!loading && notes.length === 0 ? (
        <p className="repo-empty">Capture a note first, then extract topics to see the graph.</p>
      ) : null}
      {!loading && notes.length > 0 ? (
        <div className="map-canvas">
          <ReactFlowProvider>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ duration: reduceMotion ? 0 : 400, padding: 0.2 }}
              minZoom={0.2}
              maxZoom={1.8}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
              panOnDrag
              zoomOnScroll={!reduceMotion}
              proOptions={{ hideAttribution: true }}
              colorMode={colorMode}
              onNodeClick={(_event, node) => {
                if (node.type === "note") {
                  onSelectNote(node.data.noteId);
                  return;
                }
                if (node.type === "topic") {
                  onSelectTopic(node.data.topicId, node.data.noteId);
                  onFocusCard();
                }
              }}
            >
              <Controls showInteractive={false} />
            </ReactFlow>
          </ReactFlowProvider>
        </div>
      ) : null}
    </section>
  );
}
