import type { KeyboardEvent } from "react";
import type { Topic } from "../types";

type TopicCardProps = {
  topic: Topic;
  noteTitle?: string;
  selected?: boolean;
  activeTag?: string | null;
  onTagClick?: (tag: string) => void;
  onSelect?: (topicId: number) => void;
};

export function TopicCard({
  topic,
  noteTitle,
  selected = false,
  activeTag = null,
  onTagClick,
  onSelect,
}: TopicCardProps) {
  function handleKey(event: KeyboardEvent<HTMLElement>): void {
    if (!onSelect) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(topic.id);
    }
  }

  return (
    <article
      id={`topic-card-${topic.id}`}
      className={[
        "topic-card",
        selected ? "topic-card-selected" : "",
        onSelect ? "topic-card-selectable" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={() => onSelect?.(topic.id)}
      onKeyDown={handleKey}
      tabIndex={onSelect ? 0 : undefined}
      role={onSelect ? "button" : undefined}
    >
      {noteTitle ? <p className="topic-card-note">{noteTitle}</p> : null}
      <h3>{topic.title}</h3>
      <ul>
        {topic.points.map((point) => (
          <li key={point.id}>{point.text}</li>
        ))}
      </ul>
      <div className="topic-tags">
        {topic.tags.map((tag) => {
          const tagSelected = tag.tag === activeTag;
          if (onTagClick) {
            return (
              <button
                key={tag.id}
                type="button"
                className={tagSelected ? "tag tag-active" : "tag"}
                onClick={(event) => {
                  event.stopPropagation();
                  onTagClick(tag.tag);
                }}
              >
                #{tag.tag}
              </button>
            );
          }
          return (
            <span key={tag.id} className="tag">
              #{tag.tag}
            </span>
          );
        })}
      </div>
    </article>
  );
}
