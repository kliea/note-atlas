import type { Topic } from "../types";
import { TopicCard } from "./TopicCard";

type TopicListProps = {
  topics: Topic[];
  extracting: boolean;
};

export function TopicList({ topics, extracting }: TopicListProps) {
  if (extracting) {
    return <p className="topics-status">Extracting topics…</p>;
  }
  if (topics.length === 0) {
    return <p className="topics-status">No topics yet. Open a saved note and click Extract.</p>;
  }
  return (
    <div className="topic-list">
      {topics.map((topic) => (
        <TopicCard key={topic.id} topic={topic} />
      ))}
    </div>
  );
}
