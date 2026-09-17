import type { Edge } from "@xyflow/react";
import {
  hubOrigin,
  NOTE_NODE_HEIGHT,
  NOTE_NODE_WIDTH,
  radialSlots,
  sideToward,
} from "./layout";
import type { NoteDetail, Topic } from "./types";
import type { NoteMapNode } from "./components/nodes/NoteNode";
import type { TopicMapNode } from "./components/nodes/TopicNode";

export type AtlasNode = NoteMapNode | TopicMapNode;

export function buildAtlasGraph(
  notes: NoteDetail[],
  selectedTopicId: number | null,
  linkSharedTags: boolean,
): { nodes: AtlasNode[]; edges: Edge[] } {
  const nodes: AtlasNode[] = [];
  const edges: Edge[] = [];
  const topicCenters = new Map<number, { x: number; y: number }>();

  notes.forEach((note, index) => {
    const origin = hubOrigin(index);
    const noteId = `note-${note.id}`;
    nodes.push({
      id: noteId,
      type: "note",
      position: {
        x: origin.x - NOTE_NODE_WIDTH / 2,
        y: origin.y - NOTE_NODE_HEIGHT / 2,
      },
      data: { title: note.title, source: note.source, noteId: note.id },
      draggable: false,
    });
    const slots = radialSlots(note.topics.length, origin);
    note.topics.forEach((topic, topicIndex) => {
      const slot = slots[topicIndex];
      nodes.push({
        id: `topic-${topic.id}`,
        type: "topic",
        position: { x: slot.x, y: slot.y },
        data: { title: topic.title, topicId: topic.id, noteId: note.id },
        selected: topic.id === selectedTopicId,
        draggable: false,
      });
      topicCenters.set(topic.id, { x: slot.x, y: slot.y });
      edges.push({
        id: `edge-${note.id}-${topic.id}`,
        source: noteId,
        target: `topic-${topic.id}`,
        sourceHandle: slot.sourceSide,
        targetHandle: slot.targetSide,
        selectable: false,
      });
    });
  });

  if (linkSharedTags) {
    edges.push(...tagBridges(notes, topicCenters));
  }
  return { nodes, edges };
}

function tagBridges(
  notes: NoteDetail[],
  centers: Map<number, { x: number; y: number }>,
): Edge[] {
  const byTag = new Map<string, Topic[]>();
  for (const note of notes) {
    for (const topic of note.topics) {
      for (const tag of topic.tags) {
        const list = byTag.get(tag.tag) ?? [];
        list.push(topic);
        byTag.set(tag.tag, list);
      }
    }
  }
  const edges: Edge[] = [];
  const seen = new Set<string>();
  for (const [tag, topics] of byTag) {
    const unique: Topic[] = [];
    const used = new Set<number>();
    for (const topic of topics) {
      if (used.has(topic.id)) {
        continue;
      }
      used.add(topic.id);
      unique.push(topic);
    }
    for (let i = 0; i < unique.length; i += 1) {
      for (let j = i + 1; j < unique.length; j += 1) {
        const left = unique[i];
        const right = unique[j];
        if (left.note_id === right.note_id) {
          continue;
        }
        const pair = [left.id, right.id].sort((a, b) => a - b).join("-");
        const key = `${tag}:${pair}`;
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        const from = centers.get(left.id);
        const to = centers.get(right.id);
        if (!from || !to) {
          continue;
        }
        edges.push({
          id: `tag-${key}`,
          source: `topic-${left.id}`,
          target: `topic-${right.id}`,
          sourceHandle: `out-${sideToward(from, to)}`,
          targetHandle: sideToward(to, from),
          selectable: false,
          className: "tag-edge",
          label: `#${tag}`,
        });
      }
    }
  }
  return edges;
}
