export function splitNoteText(text: string): { title: string; raw_text: string } | null {
  const trimmed = text.replace(/\s+$/u, "").replace(/^\s+/u, "");
  if (!trimmed) {
    return null;
  }
  const newline = trimmed.indexOf("\n");
  if (newline < 0) {
    return { title: trimmed, raw_text: trimmed };
  }
  const first = trimmed.slice(0, newline).trim();
  const rest = trimmed.slice(newline + 1).trim();
  const title = first || rest.split("\n")[0] || "Note";
  return { title, raw_text: rest || title };
}

export function joinNoteText(title: string, rawText: string): string {
  if (!rawText || rawText === title) {
    return title;
  }
  if (rawText.startsWith(`${title}\n`)) {
    return rawText;
  }
  return `${title}\n${rawText}`;
}
