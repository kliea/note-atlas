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

export type NoteKind = "typed" | "voice" | "ink" | "clip";

export type ExtractStatus = "idle" | "pending" | "running" | "done" | "error";

export type ContextStatus = "none" | "suggested" | "accepted" | "dismissed";

export type NoteCreate = {
  title: string;
  source: string;
  raw_text: string;
  x?: number;
  y?: number;
};

export type NoteSummary = {
  id: number;
  title: string;
  source: string;
  created_at: string;
  x: number;
  y: number;
  z: number;
  color: string | null;
  kind: NoteKind;
  pinned: boolean;
  extract_status: ExtractStatus;
};

export type NotePatch = {
  x?: number;
  y?: number;
  z?: number;
  color?: string | null;
  kind?: NoteKind;
  pinned?: boolean;
  ink_json?: string | null;
  title?: string;
  source?: string;
  raw_text?: string;
};

export type Connection = {
  id: number;
  from_note_id: number;
  to_note_id: number;
  kind: string;
  created_at: string;
};

export type ConnectionCreate = {
  from_note_id: number;
  to_note_id: number;
  kind?: string;
};

export type LinkSuggestion = {
  note_id: number;
  title: string;
  score: number;
  reason: "embedding" | "shared-tag";
};

export type Point = {
  id: number;
  topic_id: number;
  text: string;
  order_idx: number;
  context: string | null;
  context_status: ContextStatus;
};

export type PointPatch = {
  context?: string;
  context_status?: "accepted" | "dismissed";
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
  ink_json: string | null;
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
