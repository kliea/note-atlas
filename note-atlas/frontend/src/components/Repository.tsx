import { useEffect, useMemo, useState } from "react";
import { fetchNote } from "../api";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { filterTopics } from "../search";
import type { NoteSummary, Topic } from "../types";
import { TopicCard } from "./TopicCard";

type RepositoryProps = {
  notes: NoteSummary[];
  selectedTopicId: number | null;
  focusedNoteId: number | null;
  onSelectTopic: (topicId: number) => void;
};

export function Repository({
  notes,
  selectedTopicId,
  focusedNoteId,
  onSelectTopic,
}: RepositoryProps) {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [noteId, setNoteId] = useState<number | null>(focusedNoteId);
  const reduceMotion = usePrefersReducedMotion();

  useEffect(() => {
    setNoteId(focusedNoteId);
  }, [focusedNoteId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all(notes.map((note) => fetchNote(note.id)))
      .then((details) => {
        if (!cancelled) {
          setTopics(details.flatMap((note) => note.topics));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not load topics.");
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

  const noteTitles = useMemo(() => {
    const map = new Map<number, string>();
    for (const note of notes) {
      map.set(note.id, note.title);
    }
    return map;
  }, [notes]);

  const visible = useMemo(
    () => filterTopics(topics, query, activeTag, noteId, noteTitles),
    [topics, query, activeTag, noteId, noteTitles],
  );

  const scopedCount = useMemo(
    () => filterTopics(topics, "", null, noteId, noteTitles).length,
    [topics, noteId, noteTitles],
  );

  useEffect(() => {
    if (loading || selectedTopicId === null) {
      return;
    }
    const card = document.getElementById(`topic-card-${selectedTopicId}`);
    card?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
  }, [loading, selectedTopicId, visible, reduceMotion]);

  function handleTagClick(tag: string): void {
    setActiveTag((current) => (current === tag ? null : tag));
  }

  function emptyMessage(): string {
    if (scopedCount === 0) {
      return "No topics yet. Extract a note from Capture first.";
    }
    if (activeTag && query.trim()) {
      return `No topics match “${query.trim()}” with #${activeTag}.`;
    }
    if (activeTag) {
      return `No topics tagged #${activeTag}.`;
    }
    return `No topics match “${query.trim()}”.`;
  }

  return (
    <section className="repository">
      <div className="repo-toolbar">
        <label className="repo-search">
          Search
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter title, points, tags, notes…"
            autoComplete="off"
          />
        </label>
        <label className="repo-note">
          Note
          <select
            value={noteId === null ? "all" : String(noteId)}
            onChange={(event) => {
              const value = event.target.value;
              setNoteId(value === "all" ? null : Number(value));
            }}
          >
            <option value="all">All notes</option>
            {notes.map((note) => (
              <option key={note.id} value={note.id}>
                {note.title}
              </option>
            ))}
          </select>
        </label>
        <p className="repo-count" aria-live="polite">
          {visible.length} of {scopedCount} topics · {notes.length} notes
        </p>
        {activeTag ? (
          <button
            type="button"
            className="tag tag-active"
            onClick={() => setActiveTag(null)}
          >
            #{activeTag} ×
          </button>
        ) : null}
      </div>
      {loading ? <p className="topics-status">Loading topics…</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
      {!loading && !error && visible.length === 0 ? (
        <p className="repo-empty">{emptyMessage()}</p>
      ) : null}
      {!loading && visible.length > 0 ? (
        <div className="repo-grid">
          {visible.map((topic) => (
            <TopicCard
              key={topic.id}
              topic={topic}
              noteTitle={noteTitles.get(topic.note_id)}
              selected={topic.id === selectedTopicId}
              activeTag={activeTag}
              onTagClick={handleTagClick}
              onSelect={onSelectTopic}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
