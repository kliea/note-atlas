import { useCallback, useEffect, useMemo, useState, type DragEvent, type ReactNode } from "react";
import {
  addReaderLimitation,
  decideIdentity,
  deleteClaim,
  editClaim,
  fetchApiStatus,
  fetchStudies,
  fetchStudy,
  dismissLead,
  markParent,
  reextractAll,
  reextractPaper,
  refreshLeads,
  refreshParents,
  retryResolution,
  retryStudy,
  sendClaimToBoard,
  setApiEnabled,
  uploadPapers,
  type StudyFilter,
} from "../../api";
import type { ColorMode } from "@xyflow/react";
import type {
  ApiStatus,
  Claim,
  LeadItem,
  ParentMark,
  ResearchCitation,
  ResearchJob,
  StudyDetail,
  StudySummary,
} from "../../types";
import { loadBoardCentre } from "../../boardCentre";
import { ApiPill } from "./ApiPill";
import { ClaimCard } from "./ClaimCard";
import { LeadsSection } from "./LeadsSection";
import { LineageGraph } from "./LineageGraph";
import { ParentsSection } from "./ParentsSection";
import { ResearchAskPanel } from "./ResearchAskPanel";
import { UploadDialog } from "./UploadDialog";

const POLL_MS = 1200;
const FILTERS: StudyFilter[] = ["paper", "lead", "all"];
const FILTER_LABELS: Record<StudyFilter, string> = { paper: "Papers", lead: "Leads", all: "All" };
const STEP_LABELS: Record<string, string> = {
  parse: "reading PDF…",
  extract: "extracting…",
  limitations: "checking limitations…",
  parents: "finding Parents…",
};
// Job steps in pipeline order; each reader section fills in when its step is done.
const PIPELINE = ["parse", "extract", "limitations", "parents"];

type SectionState = "waiting" | "working" | "done" | "failed";

function sectionState(job: ResearchJob | null, step: string): SectionState {
  if (job === null || job.status === "done") return "done";
  const current = PIPELINE.indexOf(job.step);
  const target = PIPELINE.indexOf(step);
  if (current > target) return "done";
  if (current < target) return "waiting";
  if (job.status === "failed") return "failed";
  return job.status === "running" ? "working" : "waiting";
}

const SECTION_LABELS: Record<Exclude<SectionState, "done">, string> = {
  waiting: "waiting",
  working: "working…",
  failed: "failed · retry above",
};

function SectionHeading({ title, state, children }: { title: string; state: SectionState; children?: ReactNode }) {
  return (
    <h3 className="research-heading">
      {title}
      {state !== "done" && (
        <span className={`research-badge research-section-${state}`}>{SECTION_LABELS[state]}</span>
      )}
      {children}
    </h3>
  );
}

function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

function isActive(job: ResearchJob | null): boolean {
  return job?.status === "queued" || job?.status === "running";
}

function isResolving(study: StudySummary | null): boolean {
  return study?.resolve_status === "pending" || study?.resolve_status === "running";
}

function isFindingLeads(study: StudyDetail | null): boolean {
  return study?.leads_status === "pending" || study?.leads_status === "running";
}

function hoursUntil(iso: string | null): string {
  if (!iso) return "";
  const hours = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 3_600_000));
  return hours < 1 ? "in under an hour" : `in ~${hours} h`;
}

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function StatusBadge({ study }: { study: StudySummary }) {
  const { job } = study;
  if (job?.status === "queued") {
    return (
      <span className="research-badge research-badge-wait">
        waiting{job.queue_position ? ` (${ordinal(job.queue_position)} in line)` : ""}
      </span>
    );
  }
  if (job?.status === "running") {
    return <span className="research-badge research-badge-wait">{STEP_LABELS[job.step] ?? "working…"}</span>;
  }
  if (job?.status === "failed") {
    return <span className="research-badge research-badge-failed">failed</span>;
  }
  if (study.references_status === "unavailable") {
    return <span className="research-badge research-badge-muted">references unavailable</span>;
  }
  return null;
}

function StateBadge({ state }: { state: StudySummary["state"] }) {
  return <span className={`research-badge research-badge-${state}`}>{state === "paper" ? "Paper" : "Lead"}</span>;
}

type Linkable = Pick<StudySummary, "doi" | "arxiv_id" | "oa_url">;

function StudyLinks({ study }: { study: Linkable }) {
  if (!study.doi && !study.arxiv_id && !study.oa_url) return null;
  return (
    <span className="research-links">
      {study.oa_url && (
        <a href={study.oa_url} target="_blank" rel="noreferrer">
          PDF ↗
        </a>
      )}
      {study.arxiv_id && (
        <a href={`https://arxiv.org/abs/${study.arxiv_id}`} target="_blank" rel="noreferrer">
          arXiv ↗
        </a>
      )}
      {study.doi && (
        <a href={`https://doi.org/${study.doi}`} target="_blank" rel="noreferrer">
          DOI ↗
        </a>
      )}
    </span>
  );
}

function byline(study: StudySummary): string {
  const authors =
    study.authors.length > 3 ? `${study.authors.slice(0, 3).join(", ")} et al.` : study.authors.join(", ");
  return [authors, [study.venue, study.year].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
}

type ReaderTab = "reading" | "lineage";

// Open a Paper at one of its Claims (from a board note's Paper chip).
export type ResearchTarget = { studyId: number; claimId: number | null };

type ResearchViewProps = {
  colorMode: ColorMode;
  target: ResearchTarget | null;
  onOpenNote: (noteId: number) => void;
};

export function ResearchView({ colorMode, target, onOpenNote }: ResearchViewProps) {
  const [tab, setTab] = useState<ReaderTab>("reading");
  const [highlightClaimId, setHighlightClaimId] = useState<number | null>(target?.claimId ?? null);
  const [highlightField, setHighlightField] = useState<string | null>(null);
  const [askOpen, setAskOpen] = useState(false);
  // Papers ticked in the Library: Ask's scope (none ticked = the whole Library).
  const [askIds, setAskIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      const el = event.target as HTMLElement | null;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        setAskOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function toggleAskId(id: number): void {
    setAskIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const [filter, setFilter] = useState<StudyFilter>(target ? "all" : "paper");
  const [query, setQuery] = useState("");
  const [studies, setStudies] = useState<StudySummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(target?.studyId ?? null);

  useEffect(() => {
    if (target === null) return;
    setSelectedId(target.studyId);
    setTab("reading");
    setHighlightClaimId(target.claimId);
  }, [target]);

  const onCite = useCallback((citation: ResearchCitation) => {
    setSelectedId(citation.study_id);
    setTab("reading");
    setHighlightClaimId(citation.claim_id);
    setHighlightField(citation.field);
  }, []);
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStudies = useCallback(async () => {
    try {
      setStudies(await fetchStudies(filter, query));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [filter, query]);

  const loadDetail = useCallback(async () => {
    if (selectedId === null) {
      setDetail(null);
      return;
    }
    try {
      setDetail(await fetchStudy(selectedId));
    } catch {
      setDetail(null);
    }
  }, [selectedId]);

  useEffect(() => {
    void loadStudies();
  }, [loadStudies]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const [apiStatus, setApiStatus] = useState<ApiStatus | null>(null);

  const loadApiStatus = useCallback(async () => {
    try {
      setApiStatus(await fetchApiStatus());
    } catch {
      setApiStatus(null);
    }
  }, []);

  useEffect(() => {
    void loadApiStatus();
  }, [loadApiStatus]);

  const busy = useMemo(
    () =>
      studies.some((s) => isActive(s.job) || isResolving(s)) ||
      isActive(detail?.job ?? null) ||
      isResolving(detail) ||
      isFindingLeads(detail),
    [studies, detail],
  );

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      void loadStudies();
      void loadDetail();
      void loadApiStatus();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, loadStudies, loadDetail, loadApiStatus]);

  const upload = useCallback(
    async (files: File[]) => {
      const pdfs = files.filter(isPdf);
      if (pdfs.length === 0) {
        setError("Only PDF files can be uploaded.");
        return;
      }
      try {
        const created = await uploadPapers(pdfs);
        setFilter("paper");
        if (created[0]) setSelectedId(created[0].id);
        await loadStudies();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [loadStudies],
  );

  const retry = useCallback(
    async (id: number) => {
      try {
        setDetail(await retryStudy(id));
        await loadStudies();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [loadStudies],
  );

  const toggleApi = useCallback(async () => {
    if (apiStatus === null) return;
    try {
      setApiStatus(await setApiEnabled(!apiStatus.enabled));
      await loadStudies();
      await loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [apiStatus, loadStudies, loadDetail]);

  const answerIdentity = useCallback(
    async (same: boolean) => {
      if (selectedId === null) return;
      try {
        setDetail(await decideIdentity(selectedId, same));
        await loadStudies();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [selectedId, loadStudies],
  );

  const retryResolve = useCallback(async () => {
    if (selectedId === null) return;
    setDetail(await retryResolution(selectedId));
  }, [selectedId]);

  const onMarkParent = useCallback(
    async (studyId: number, mark: ParentMark | null) => {
      if (selectedId === null) return;
      try {
        setDetail(await markParent(selectedId, studyId, mark));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [selectedId],
  );

  const onReextract = useCallback(async () => {
    if (selectedId === null) return;
    try {
      setDetail(await reextractPaper(selectedId));
      await loadStudies();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [selectedId, loadStudies]);

  const onReextractAll = useCallback(async () => {
    const ok = window.confirm(
      "Re-extract every Paper with the current model? Your edits, sent Claims, your own Limitations, and deletions are kept.",
    );
    if (!ok) return;
    try {
      const { queued, busy } = await reextractAll();
      setError(busy > 0 ? `Queued ${queued}; ${busy} already being processed were skipped.` : null);
      await loadStudies();
      await loadDetail();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [loadStudies, loadDetail]);

  const onSendClaim = useCallback(
    async (claimId: number) => {
      try {
        setDetail(await sendClaimToBoard(claimId, loadBoardCentre()));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [],
  );

  const onDismissLead = useCallback(
    async (studyId: number) => {
      if (selectedId === null) return;
      try {
        setDetail(await dismissLead(selectedId, studyId, true));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [selectedId],
  );

  const onRefreshLeads = useCallback(async () => {
    if (selectedId === null) return;
    try {
      setDetail(await refreshLeads(selectedId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [selectedId]);

  const onRefreshParents = useCallback(async () => {
    if (selectedId === null) return;
    try {
      setDetail(await refreshParents(selectedId));
      await loadStudies();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [selectedId, loadStudies]);

  const onEditClaim = useCallback(
    async (id: number, text: string) => {
      await editClaim(id, text);
      await loadDetail();
    },
    [loadDetail],
  );

  const onDeleteClaim = useCallback(
    async (id: number) => {
      await deleteClaim(id);
      await loadDetail();
    },
    [loadDetail],
  );

  const onAddLimitation = useCallback(
    async (text: string) => {
      if (selectedId === null) return;
      await addReaderLimitation(selectedId, text);
      await loadDetail();
    },
    [selectedId, loadDetail],
  );

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    void upload(Array.from(event.dataTransfer.files));
  }

  return (
    <div
      className={`research ${dragging ? "research-dragging" : ""}`}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragging(false);
      }}
      onDrop={onDrop}
    >
      <section className="research-library" aria-label="Library">
        <div className="research-row">
          <input
            className="research-search"
            type="search"
            placeholder="Search studies…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search studies"
          />
          <button type="button" className="nav-btn" onClick={() => setUploadOpen(true)}>
            + Upload PDF
          </button>
          <button
            type="button"
            className="nav-btn"
            onClick={() => setAskOpen(true)}
            title="Ask across the ticked Papers, or the whole Library (shortcut: /)"
          >
            Ask /
          </button>
        </div>
        <div className="research-row research-api-row">
          <ApiPill status={apiStatus} onToggle={() => void toggleApi()} />
          <button
            type="button"
            className="research-link-btn"
            onClick={() => void onReextractAll()}
            title="After a model or parser upgrade: re-run extraction on every Paper"
          >
            re-extract all
          </button>
        </div>
        <div className="research-row research-chips" role="group" aria-label="Filter studies">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              className={`research-chip ${filter === f ? "on" : ""}`}
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>
        {error && (
          <p className="research-error" role="alert">
            {error}
          </p>
        )}
        {studies.length === 0 ? (
          <div className="research-empty">
            {filter === "lead"
              ? "No Leads yet. Every reference in an uploaded Paper becomes a Lead."
              : "No Papers yet. Drop a PDF anywhere here, or use + Upload PDF."}
          </div>
        ) : (
          <table className="research-table">
            <thead>
              <tr>
                <th>
                  <span className="visually-hidden">Include in Ask</span>
                </th>
                <th>Title</th>
                <th>Year</th>
                <th>Refs</th>
                <th>
                  <span className="visually-hidden">Status</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {studies.map((study) => (
                <tr
                  key={study.id}
                  className={study.id === selectedId ? "sel" : ""}
                  onClick={() => setSelectedId(study.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(study.id);
                    }
                  }}
                  tabIndex={0}
                  aria-selected={study.id === selectedId}
                >
                  <td onClick={(event) => event.stopPropagation()}>
                    {study.state === "paper" && (
                      <input
                        type="checkbox"
                        checked={askIds.has(study.id)}
                        onChange={() => toggleAskId(study.id)}
                        aria-label={`Include ${study.title} in Ask`}
                      />
                    )}
                  </td>
                  <td>
                    {study.title} {filter === "all" && <StateBadge state={study.state} />}
                  </td>
                  <td>{study.year ?? "—"}</td>
                  <td>{study.state === "paper" ? study.reference_count : "—"}</td>
                  <td>
                    <StatusBadge study={study} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="research-reader" aria-label="Reader">
        {askOpen && (
          <ResearchAskPanel
            studyIds={[...askIds]}
            scopeLabel={
              askIds.size === 0 ? "the whole Library" : `${askIds.size} selected Paper${askIds.size === 1 ? "" : "s"}`
            }
            onCite={onCite}
            onClose={() => setAskOpen(false)}
          />
        )}
        {detail === null ? (
          <p className="research-muted">Select a Paper or Lead to read it here.</p>
        ) : (
          <>
            <h2 className="research-title">
              {detail.title} <StateBadge state={detail.state} /> <StatusBadge study={detail} />
            </h2>
            <p className="research-muted">
              {byline(detail)} <StudyLinks study={detail} />
            </p>
            {detail.state === "paper" && (
              <div className="research-row research-chips" role="tablist" aria-label="Paper view">
                {(["reading", "lineage"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    role="tab"
                    aria-selected={tab === t}
                    className={`research-chip ${tab === t ? "on" : ""}`}
                    onClick={() => setTab(t)}
                  >
                    {t === "reading" ? "Reading" : "Lineage"}
                  </button>
                ))}
              </div>
            )}
            {detail.state === "paper" && tab === "lineage" ? (
              <>
                <LeadsNotice detail={detail} onRefresh={() => void onRefreshLeads()} onTurnOn={() => void toggleApi()} />
                <LineageGraph detail={detail} colorMode={colorMode} onOpen={setSelectedId} />
              </>
            ) : (
              <>
              {detail.job?.status === "failed" && (
                <div className="research-callout research-callout-error">
                  <span>Processing failed: {detail.job.error}</span>
                  <button type="button" className="nav-btn" onClick={() => void retry(detail.id)}>
                    Retry from {detail.job.step}
                  </button>
                </div>
              )}
              {detail.possible_match && (
                <div className="research-callout research-callout-question">
                  <span>
                    Is this the Lead you already have? <strong>{detail.possible_match.title}</strong>
                    {detail.possible_match.year ? ` (${detail.possible_match.year})` : ""}
                  </span>
                  <span className="research-row">
                    <button type="button" className="nav-btn" onClick={() => void answerIdentity(true)}>
                      Yes, same work
                    </button>
                    <button type="button" className="nav-btn" onClick={() => void answerIdentity(false)}>
                      No
                    </button>
                  </span>
                </div>
              )}
              {detail.state === "paper" && <ResolveNotice detail={detail} onRetry={() => void retryResolve()} onTurnOn={() => void toggleApi()} />}
              {detail.state === "lead" && (
                <div className="research-callout">
                  This is a Lead — Atlas knows it from a reference list, not its PDF. Upload its PDF to read it.
                </div>
              )}
              {detail.references_status === "unavailable" && (
                <div className="research-callout">
                  References unavailable: the PDF parser wasn't reachable, so only plain text was kept.
                </div>
              )}
              {detail.state === "paper" && (
                <PaperExtraction
                  detail={detail}
                  onEdit={onEditClaim}
                  onDelete={onDeleteClaim}
                  onAddLimitation={onAddLimitation}
                  onSend={onSendClaim}
                  onReextract={() => void onReextract()}
                  onOpenNote={onOpenNote}
                  highlightClaimId={highlightClaimId}
                  highlightField={highlightField}
                />
              )}
              {detail.state === "paper" && (
                <>
                  <SectionHeading title="Parent Papers" state={sectionState(detail.job, "parents")}>
                    {sectionState(detail.job, "parents") === "done" && (
                      <button
                        type="button"
                        className="research-link-btn research-heading-action"
                        onClick={() => void onRefreshParents()}
                        title="Re-run Parent selection. Your marks are kept."
                      >
                        refresh
                      </button>
                    )}
                  </SectionHeading>
                  {sectionState(detail.job, "parents") === "done" && (
                    <ParentsSection
                      parents={detail.parents}
                      onMark={onMarkParent}
                      onOpen={setSelectedId}
                      links={(parent) => <StudyLinks study={parent} />}
                    />
                  )}
                  <PaperLeads
                    detail={detail}
                    onDismiss={onDismissLead}
                    onRefresh={() => void onRefreshLeads()}
                    onTurnOn={() => void toggleApi()}
                    onOpen={setSelectedId}
                  />
                </>
              )}
              {detail.abstract && (
                <details className="research-abstract">
                  <summary>Abstract</summary>
                  <p>{detail.abstract}</p>
                </details>
              )}
              {detail.state === "paper" && detail.references.length > 0 && (
                <>
                  <h3 className="research-heading">References ({detail.references.length})</h3>
                  <ol className="research-references">
                    {detail.references.map((ref) => (
                      <li key={ref.study_id}>
                        <button type="button" className="research-link-btn" onClick={() => setSelectedId(ref.study_id)}>
                          {ref.title}
                        </button>
                        <span className="research-muted">
                          {ref.year ? ` · ${ref.year}` : ""}
                          {ref.mention_count > 0 ? ` · cited ${ref.mention_count}×` : ""}
                        </span>{" "}
                        <StateBadge state={ref.state} /> <StudyLinks study={ref} />
                      </li>
                    ))}
                  </ol>
                </>
              )}
              </>
            )}
          </>
        )}
      </section>

      {uploadOpen && (
        <UploadDialog
          onClose={() => setUploadOpen(false)}
          onFiles={(files) => {
            setUploadOpen(false);
            void upload(files);
          }}
        />
      )}
    </div>
  );
}

type PaperExtractionProps = {
  detail: StudyDetail;
  onEdit: (id: number, text: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onAddLimitation: (text: string) => Promise<void>;
  onSend: (id: number) => Promise<void>;
  onReextract: () => void;
  onOpenNote: (noteId: number) => void;
  highlightClaimId: number | null;
  highlightField: string | null;
};

function provenance(detail: StudyDetail): string {
  const date = detail.extracted_at ? new Date(detail.extracted_at).toLocaleDateString() : null;
  return [detail.extraction_model, detail.extraction_parser, date].filter(Boolean).join(" · ");
}

const FIELDS: { key: "research_question" | "method" | "key_results" | "scope"; label: string }[] = [
  { key: "research_question", label: "Research question" },
  { key: "method", label: "Method" },
  { key: "key_results", label: "Key results" },
  { key: "scope", label: "Scope" },
];

function PaperExtraction({
  detail,
  onEdit,
  onDelete,
  onAddLimitation,
  onSend,
  onReextract,
  onOpenNote,
  highlightClaimId,
  highlightField,
}: PaperExtractionProps) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const fieldsState = sectionState(detail.job, "extract");
  const limitationsState = sectionState(detail.job, "limitations");
  const contributions = detail.claims.filter((c) => c.kind === "contribution");

  useEffect(() => {
    if (highlightField === null) return;
    document.querySelector(".research-field-highlight")?.scrollIntoView({ block: "center" });
  }, [highlightField, detail.id]);
  const limitations = detail.claims.filter((c) => c.kind === "limitation");

  async function add(): Promise<void> {
    const text = draft.trim();
    if (!text) return;
    await onAddLimitation(text);
    setDraft("");
    setAdding(false);
  }

  function claimList(claims: Claim[], empty: string) {
    if (claims.length === 0) return empty ? <p className="research-muted">{empty}</p> : null;
    return (
      <ul className="research-claims">
        {claims.map((claim) => (
          <ClaimCard
            key={claim.id}
            claim={claim}
            onEdit={onEdit}
            onDelete={onDelete}
            onSend={onSend}
            onOpenNote={onOpenNote}
            highlighted={claim.id === highlightClaimId}
          />
        ))}
      </ul>
    );
  }

  return (
    <>
      <SectionHeading title="Extraction" state={fieldsState}>
        {fieldsState === "done" && detail.extracted_at && !isActive(detail.job) && (
          <button
            type="button"
            className="research-link-btn research-heading-action"
            onClick={onReextract}
            title="Run extraction again. Your edits, sent Claims, your own Limitations, and deletions are kept."
          >
            re-extract
          </button>
        )}
      </SectionHeading>
      {fieldsState === "done" && detail.extracted_at && (
        <p className="research-muted research-provenance">Extracted with {provenance(detail)}</p>
      )}
      {fieldsState === "done" && (
        <dl className="research-fields">
          {FIELDS.map(({ key, label }) => (
            <div key={key} className={key === highlightField ? "research-field-highlight" : undefined}>
              <dt>{label}</dt>
              <dd>{detail[key] ?? <span className="research-muted">not found</span>}</dd>
            </div>
          ))}
        </dl>
      )}

      <SectionHeading title="Contributions" state={fieldsState} />
      {fieldsState === "done" && claimList(contributions, "No contributions found.")}

      <SectionHeading title="Limitations" state={limitationsState}>
        {!adding && (
          <button type="button" className="research-link-btn research-heading-action" onClick={() => setAdding(true)}>
            + add yours
          </button>
        )}
      </SectionHeading>
      {adding && (
        <div className="research-claim-edit">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void add();
              if (event.key === "Escape") setAdding(false);
            }}
            rows={2}
            placeholder="A limitation you see in this paper"
            autoFocus
            aria-label="Your limitation"
          />
          <div className="research-row">
            <button type="button" className="nav-btn" onClick={() => void add()}>
              Add
            </button>
            <button type="button" className="nav-btn" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {limitationsState === "done"
        ? claimList(limitations, "The paper admits no limitations that could be verified against its text.")
        : claimList(limitations.filter((c) => c.author === "reader"), "")}
    </>
  );
}

function ResolveNotice({
  detail,
  onRetry,
  onTurnOn,
}: {
  detail: StudyDetail;
  onRetry: () => void;
  onTurnOn: () => void;
}) {
  switch (detail.resolve_status) {
    case "pending":
    case "running":
      return <p className="research-muted">Looking up year, DOI, and references on OpenAlex…</p>;
    case "waiting_budget":
      return (
        <div className="research-callout">
          Waiting for today's OpenAlex budget (resets {hoursUntil(detail.resolve_after)}). Year, DOI, and links fill in
          then; everything else is ready now.
        </div>
      );
    case "off":
      return (
        <div className="research-callout">
          <span>The scholarly API is off, so year, DOI, and links come only from the PDF.</span>
          <button type="button" className="nav-btn" onClick={onTurnOn}>
            Turn on
          </button>
        </div>
      );
    case "failed":
      return (
        <div className="research-callout research-callout-error">
          <span>Couldn't look this paper up: {detail.resolve_error}</span>
          <button type="button" className="nav-btn" onClick={onRetry}>
            Retry
          </button>
        </div>
      );
    default:
      return null;
  }
}

function describeSibling(lead: LeadItem): string {
  const parents = `cites ${lead.shared} of this paper's Parents`;
  return lead.similarity === null ? parents : `${parents} · ${Math.round(lead.similarity * 100)}% similar`;
}

function describeAncestor(lead: LeadItem): string {
  const via = lead.hop === 1 ? "Parents" : "Ancestors";
  const cited = `cited by ${lead.shared} of this paper's ${via}`;
  return lead.fwci === null ? cited : `${cited} · FWCI ${lead.fwci.toFixed(1)}`;
}

function LeadsNotice({
  detail,
  onRefresh,
  onTurnOn,
}: {
  detail: StudyDetail;
  onRefresh: () => void;
  onTurnOn: () => void;
}) {
  switch (detail.leads_status) {
    case "pending":
    case "running":
      return <p className="research-muted">Finding Siblings and Ancestors…</p>;
    case "waiting_budget":
      return (
        <div className="research-callout">
          Waiting for today's OpenAlex budget (resets {hoursUntil(detail.leads_after)}) to find Siblings and Ancestors.
        </div>
      );
    case "failed":
      return (
        <div className="research-callout research-callout-error">
          <span>Couldn't find Siblings and Ancestors: {detail.leads_error}</span>
          <button type="button" className="nav-btn" onClick={onRefresh}>
            Retry
          </button>
        </div>
      );
    default:
      return detail.leads_api_off ? (
        <div className="research-callout">
          <span>
            The scholarly API is off, so Siblings come only from your Library and Ancestors only through uploaded
            Parents.
          </span>
          <button type="button" className="nav-btn" onClick={onTurnOn}>
            Turn on
          </button>
        </div>
      ) : null;
  }
}

type PaperLeadsProps = {
  detail: StudyDetail;
  onDismiss: (studyId: number) => Promise<void>;
  onRefresh: () => void;
  onTurnOn: () => void;
  onOpen: (studyId: number) => void;
};

function PaperLeads({ detail, onDismiss, onRefresh, onTurnOn, onOpen }: PaperLeadsProps) {
  if (sectionState(detail.job, "parents") !== "done") return null;
  const settled = detail.leads_status === "done";
  const links = (lead: LeadItem) => <StudyLinks study={lead} />;
  const hops = [1, 2].map((hop) => detail.ancestors.filter((a) => a.hop === hop));
  return (
    <>
      <h3 className="research-heading">
        Siblings
        {settled && (
          <button
            type="button"
            className="research-link-btn research-heading-action"
            onClick={onRefresh}
            title="Find Siblings and Ancestors again. Leads you marked not relevant stay hidden."
          >
            refresh leads
          </button>
        )}
      </h3>
      <LeadsNotice detail={detail} onRefresh={onRefresh} onTurnOn={onTurnOn} />
      {settled && (
        <LeadsSection
          leads={detail.siblings}
          shown={5}
          empty="No Siblings found: nothing else cites this paper's Parents yet."
          describe={describeSibling}
          onDismiss={onDismiss}
          onOpen={onOpen}
          links={links}
        />
      )}
      <h3 className="research-heading">Ancestors</h3>
      {settled &&
        (detail.ancestors.length === 0 ? (
          <p className="research-muted">No Ancestors found: none of this paper's Parents has a known reference list.</p>
        ) : (
          hops.map(
            (leads, index) =>
              leads.length > 0 && (
                <div key={index}>
                  <p className="research-muted">{index === 0 ? "What its Parents build on" : "One step further back"}</p>
                  <LeadsSection
                    leads={leads}
                    shown={3}
                    empty=""
                    describe={describeAncestor}
                    onDismiss={onDismiss}
                    onOpen={onOpen}
                    links={links}
                  />
                </div>
              ),
          )
        ))}
    </>
  );
}
