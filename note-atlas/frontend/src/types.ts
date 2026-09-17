export type HealthResponse = {
  status: string;
};

export type LlmPingResponse = {
  reachable: boolean;
  model: string;
  host: string;
  model_present: boolean;
  error: string | null;
};

export type PillState = "loading" | "ok" | "error";

export type NoteCreate = {
  title: string;
  source: string;
  raw_text: string;
};

export type NoteSummary = {
  id: number;
  title: string;
  source: string;
  created_at: string;
};

export type Point = {
  id: number;
  topic_id: number;
  text: string;
  order_idx: number;
};

export type Tag = {
  id: number;
  topic_id: number;
  tag: string;
};

export type Topic = {
  id: number;
  note_id: number;
  title: string;
  order_idx: number;
  points: Point[];
  tags: Tag[];
};

export type NoteDetail = NoteSummary & {
  raw_text: string;
  topics: Topic[];
};

export type Citation = {
  note_id: number;
  note_title: string;
  topic_id: number | null;
  topic_title: string | null;
  score: number;
};

export type AskMeta = {
  grounded: boolean;
  citations: Citation[];
};
