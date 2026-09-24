import type { ApiStatus } from "../../types";

type ApiPillProps = {
  status: ApiStatus | null;
  onToggle: () => void;
};

function money(value: number): string {
  return `$${value.toFixed(value < 0.1 ? 3 : 2)}`;
}

function label(status: ApiStatus): string {
  if (!status.enabled) return "Scholarly API · off";
  const parts = ["OpenAlex · on"];
  if (status.remaining_usd !== null) parts.push(`${money(status.remaining_usd)} left today`);
  if (status.waiting > 0) parts.push(`${status.waiting} waiting`);
  return parts.join(" · ") + (status.s2_key ? " + S2" : "");
}

function explanation(status: ApiStatus): string {
  const sends = "Only titles, DOIs, and OpenAlex ids are sent — never PDFs or notes.";
  if (!status.enabled) {
    return `Off: year, DOI, and links come only from the PDF. Click to turn on. ${sends}`;
  }
  const key = status.openalex_key
    ? "Using your OpenAlex key ($1/day)."
    : "No OpenAlex key: $0.10/day. Set OPENALEX_API_KEY in .env for $1/day.";
  return `${key} Click to turn off. ${sends}`;
}

export function ApiPill({ status, onToggle }: ApiPillProps) {
  if (status === null) return null;
  const exhausted = status.enabled && status.remaining_usd !== null && status.remaining_usd <= 0;
  const tone = !status.enabled ? "pill-loading" : exhausted ? "pill-error" : "pill-ok";
  return (
    <button
      type="button"
      className={`pill research-api-pill ${tone}`}
      onClick={onToggle}
      aria-pressed={status.enabled}
      title={explanation(status)}
    >
      {label(status)}
    </button>
  );
}
