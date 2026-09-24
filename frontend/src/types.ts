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

// Research Track: a Study is a Lead (no PDF) or a Paper.
export type StudyState = "lead" | "paper";

export type ResolveStatus = "pending" | "running" | "done" | "waiting_budget" | "off" | "failed";

export type ApiStatus = {
  enabled: boolean;
  openalex_key: boolean;
  s2_key: boolean;
  remaining_usd: number | null;
  limit_usd: number | null;
  reset_at: string | null;
  waiting: number;
};

export type ParentMark = "pinned" | "unpinned";

export type ParentItem = {
  study_id: number;
  state: StudyState;
  title: string;
  year: number | null;
  doi: string | null;
  arxiv_id: string | null;
  oa_url: string | null;
  mention_count: number;
  score: number | null;
  reason: string | null;
  mark: ParentMark | null;
  is_parent: boolean;
};

export type LeadKind = "sibling" | "ancestor";

export type LeadItem = {
  study_id: number;
  state: StudyState;
  title: string;
  year: number | null;
  doi: string | null;
  arxiv_id: string | null;
  oa_url: string | null;
  kind: LeadKind;
  hop: number;
  shared: number;
  similarity: number | null;
  fwci: number | null;
  via: number[];
};

export type LeadsStatus = "pending" | "running" | "done" | "failed" | "waiting_budget";

export type PossibleMatch = {
  study_id: number;
  title: string;
  year: number | null;
  authors: string[];
};

export type ResearchJob = {
  status: "queued" | "running" | "done" | "failed";
  step: string;
  error: string | null;
  queue_position: number | null;
};

export type StudySummary = {
  id: number;
  state: StudyState;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  openalex_id: string | null;
  oa_url: string | null;
  reference_count: number;
  references_status: "ok" | "unavailable" | null;
  resolve_status: ResolveStatus | null;
  resolve_after: string | null;
  job: ResearchJob | null;
  created_at: string;
};

export type ReferenceItem = {
  study_id: number;
  state: StudyState;
  title: string;
  authors: string[];
  year: number | null;
  doi: string | null;
  arxiv_id: string | null;
  oa_url: string | null;
  raw_reference: string;
  mention_count: number;
};

export type Claim = {
  id: number;
  kind: "contribution" | "limitation";
  author: "paper" | "reader";
  text: string;
  quote: string | null;
  edited: boolean;
  original_text: string | null;
  stale: boolean;
};

export type StudyDetail = StudySummary & {
  abstract: string | null;
  original_filename: string | null;
  research_question: string | null;
  method: string | null;
  key_results: string | null;
  scope: string | null;
  extraction_model: string | null;
  extracted_at: string | null;
  resolve_error: string | null;
  possible_match: PossibleMatch | null;
  claims: Claim[];
  parents: ParentItem[];
  siblings: LeadItem[];
  ancestors: LeadItem[];
  leads_status: LeadsStatus | null;
  leads_error: string | null;
  leads_after: string | null;
  leads_api_off: boolean;
  references: ReferenceItem[];
};
