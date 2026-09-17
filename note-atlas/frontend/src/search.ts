import type { Topic } from "./types";

export function topicMatches(
  topic: Topic,
  query: string,
  tag: string | null,
): boolean {
  if (tag !== null && !topic.tags.some((item) => item.tag === tag)) {
    return false;
  }
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) {
    return true;
  }
  if (topic.title.toLowerCase().includes(needle)) {
    return true;
  }
  if (topic.points.some((point) => point.text.toLowerCase().includes(needle))) {
    return true;
  }
  return topic.tags.some((item) => {
    const value = item.tag.toLowerCase();
    return value.includes(needle) || `#${value}`.includes(needle);
  });
}

export function filterTopics(
  topics: Topic[],
  query: string,
  tag: string | null,
  noteId: number | null,
  noteTitles: Map<number, string> = new Map(),
): Topic[] {
  return topics.filter((topic) => {
    if (noteId !== null && topic.note_id !== noteId) {
      return false;
    }
    if (tag !== null && !topic.tags.some((item) => item.tag === tag)) {
      return false;
    }
    const needle = query.trim().toLowerCase();
    if (needle.length === 0) {
      return true;
    }
    const noteTitle = noteTitles.get(topic.note_id) ?? "";
    if (noteTitle.toLowerCase().includes(needle)) {
      return true;
    }
    return topicMatches(topic, query, null);
  });
}
