import type { ApiStatus, ScholarlySource } from "../../types";

type ApiPillProps = {
  status: ApiStatus | null;
  onToggle: () => void;
  onSource: (source: ScholarlySource) => void;
};

const SOURCE_LABELS: Record<ScholarlySource, string> = { openalex: "OpenAlex", s2: "Semantic Scholar" };

function money(value: number): string {
  return `$${value.toFixed(value < 0.1 ? 3 : 2)}`;
}

function label(status: ApiStatus): string {
  if (!status.enabled) return "Scholarly API · off";
  const parts = [`${SOURCE_LABELS[status.source]} · on`];
  if (status.source === "openalex" && status.remaining_usd !== null) {
    parts.push(`${money(status.remaining_usd)} left today`);
  }
  if (status.waiting > 0) parts.push(`${status.waiting} waiting`);
  return parts.join(" · ") + (status.source === "openalex" && status.s2_key ? " + S2" : "");
}

function explanation(status: ApiStatus): string {
  const sends = "Only titles and identifiers (DOI, arXiv, source ids) are sent — never PDFs or notes.";
  if (!status.enabled) {
    return `Off: year, DOI, and links come only from the PDF. Click to turn on. ${sends}`;
  }
  const key =
    status.source === "s2"
      ? "Using your Semantic Scholar key (about 1 request a second, so large Papers take a minute)."
      : status.openalex_key
        ? "Using your OpenAlex key ($1/day)."
        : "No OpenAlex key: $0.10/day. Set OPENALEX_API_KEY in .env for $1/day.";
  return `${key} Click to turn off. ${sends}`;
}

export function ApiPill({ status, onToggle, onSource }: ApiPillProps) {
  if (status === null) return null;
  const exhausted =
    status.enabled && status.source === "openalex" && status.remaining_usd !== null && status.remaining_usd <= 0;
  const tone = !status.enabled ? "pill-loading" : exhausted ? "pill-error" : "pill-ok";
  return (
    <>
      <button
        type="button"
        className={`pill research-api-pill ${tone}`}
        onClick={onToggle}
        aria-pressed={status.enabled}
        title={explanation(status)}
      >
        {label(status)}
      </button>
      {status.sources.length > 1 && (
        <select
          className="research-source-select"
          value={status.source}
          onChange={(event) => onSource(event.target.value as ScholarlySource)}
          aria-label="Scholarly source"
          title="Where Papers are resolved and Leads found. Switching re-resolves every Paper."
        >
          {status.sources.map((source) => (
            <option key={source} value={source}>
              {SOURCE_LABELS[source]}
            </option>
          ))}
        </select>
      )}
    </>
  );
}
