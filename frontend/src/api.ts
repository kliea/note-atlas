import type {
  AskMeta,
  Citation,
  Connection,
  ConnectionCreate,
  HealthResponse,
  LinkSuggestion,
  LlmPingResponse,
  NoteCreate,
  NoteDetail,
  NotePatch,
  NoteSummary,
  Point,
  PointPatch,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${path} failed: ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        body.detail !== undefined
      ) {
        detail = String(body.detail);
      }
    } catch {
      // Keep the status line when the body is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export function fetchLlmPing(): Promise<LlmPingResponse> {
  return requestJson<LlmPingResponse>("/llm/ping");
}

export function fetchNotes(): Promise<NoteSummary[]> {
  return requestJson<NoteSummary[]>("/notes");
}

export function fetchNote(id: number): Promise<NoteDetail> {
  return requestJson<NoteDetail>(`/notes/${id}`);
}

export function fetchSuggestions(id: number): Promise<LinkSuggestion[]> {
  return requestJson<LinkSuggestion[]>(`/notes/${id}/suggestions`);
}

export function createNote(payload: NoteCreate): Promise<NoteDetail> {
  return requestJson<NoteDetail>("/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchNote(id: number, payload: NotePatch): Promise<NoteDetail> {
  return requestJson<NoteDetail>(`/notes/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchPoint(id: number, payload: PointPatch): Promise<Point> {
  return requestJson<Point>(`/points/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteNote(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`delete note failed: ${response.status}`);
  }
}

export function fetchConnections(): Promise<Connection[]> {
  return requestJson<Connection[]>("/connections");
}

export function createConnection(payload: ConnectionCreate): Promise<Connection> {
  return requestJson<Connection>("/connections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteConnection(id: number): Promise<void> {
  const response = await fetch(
    `${API_BASE}/connections/${id}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new Error(`delete connection failed: ${response.status}`);
  }
}

export async function downloadNoteExport(
  id: number,
  format: "json" | "markdown",
): Promise<void> {
  const response = await fetch(`${API_BASE}/notes/${id}/export?format=${format}`);
  if (!response.ok) {
    throw new Error(`export failed: ${response.status}`);
  }
  const blob = await response.blob();
  const extension = format === "json" ? "json" : "md";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `note-${id}.${extension}`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function importNoteFile(file: File): Promise<NoteDetail> {
  const text = await file.text();
  const name = file.name.toLowerCase();
  let payload: unknown;
  if (name.endsWith(".md") || name.endsWith(".markdown")) {
    payload = { format: "markdown", text };
  } else {
    payload = JSON.parse(text) as unknown;
  }
  return requestJson<NoteDetail>("/notes/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

type AskHandlers = {
  onMeta: (meta: AskMeta) => void;
  onToken: (text: string) => void;
  onError?: (detail: string) => void;
};

function isAskMeta(value: unknown): value is AskMeta {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as { grounded?: unknown; citations?: unknown };
  return typeof record.grounded === "boolean" && Array.isArray(record.citations);
}

function isCitation(value: unknown): value is Citation {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.note_id === "number" &&
    typeof record.note_title === "string" &&
    (record.topic_id === null || typeof record.topic_id === "number") &&
    (record.topic_title === null || typeof record.topic_title === "string") &&
    typeof record.score === "number"
  );
}

function dispatchSse(event: string, raw: string, handlers: AskHandlers): void {
  if (!raw) {
    return;
  }
  const payload: unknown = JSON.parse(raw);
  if (event === "meta" && isAskMeta(payload)) {
    handlers.onMeta({
      grounded: payload.grounded,
      citations: payload.citations.filter(isCitation),
    });
    return;
  }
  if (
    event === "token" &&
    typeof payload === "object" &&
    payload !== null &&
    "text" in payload &&
    typeof payload.text === "string"
  ) {
    handlers.onToken(payload.text);
    return;
  }
  if (
    event === "error" &&
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload
  ) {
    handlers.onError?.(String(payload.detail));
  }
}

export async function streamAsk(
  question: string,
  handlers: AskHandlers,
  signal?: AbortSignal,
  noteIds?: number[],
): Promise<void> {
  const payload: { question: string; note_ids?: number[] } = { question };
  if (noteIds && noteIds.length > 0) {
    payload.note_ids = noteIds;
  }
  const response = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || response.body === null) {
    throw new Error(`ask failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    let split = buffer.indexOf("\n\n");
    while (split >= 0) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      dispatchSse(eventName, dataLines.join("\n"), handlers);
      split = buffer.indexOf("\n\n");
    }
    if (done) {
      break;
    }
  }
}
