"""The Research Track job queue: one worker, one Paper at a time, resumable by step.

Each upload queues a job that walks STEPS in order. The job records the next step
to run, so a restart resumes where it stopped and a retry re-runs only the step
that failed. Later slices append steps (extract, resolve, parents, leads).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from io import BytesIO

from pypdf import PdfReader

from app import (
    grobid,
    openalex,
    paper_extract,
    paper_leads,
    paper_parents,
    reextract,
    research_ask,
    research_store,
    s2,
    scholarly,
)
from app.config import ollama_model
from app.works import BudgetExhausted
from app.tei import body_text, full_text, parse_tei

log = logging.getLogger(__name__)

# Stop GROBID once the queue has been empty this long (only if Atlas started it).
GROBID_IDLE_STOP_SECONDS = 120.0
_POLL_SECONDS = 5.0


def _step_parse(study_id: int) -> None:
    """GROBID → metadata + References as Leads; falls back to plain text without References."""
    pdf = research_store.pdf_path(study_id)
    pdf_bytes = pdf.read_bytes()
    try:
        tei = grobid.process_fulltext(pdf_bytes)
        parsed = parse_tei(tei)
    except (grobid.GrobidUnavailable, ET.ParseError) as exc:
        log.warning("GROBID unavailable for study %s, using text only: %s", study_id, exc)
        text = "\n\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)
        pdf.with_suffix(".txt").write_text(text, encoding="utf-8")
        research_store.apply_text_only(study_id)
        _queue_resolution(study_id)
        return
    pdf.with_suffix(".tei.xml").write_text(tei, encoding="utf-8")
    research_store.apply_parse(study_id, parsed)
    _queue_resolution(study_id)


def _queue_resolution(study_id: int) -> None:
    """Metadata and References resolve on the network worker, alongside local extraction."""
    research_store.set_resolve_status(study_id, "pending")
    resolver.notify()


def _paper_text(study_id: int) -> tuple[str, str, str, str]:
    """(title, abstract, body, full text) from the parse output: TEI, or the plain-text fallback."""
    pdf = research_store.pdf_path(study_id)
    study = research_store.get_study(study_id)
    if study is None:
        raise LookupError(f"study {study_id} not found")
    tei_file = pdf.with_suffix(".tei.xml")
    if tei_file.exists():
        tei = tei_file.read_text(encoding="utf-8")
        body = body_text(parse_tei(tei))
        return study.title, study.abstract or "", body, full_text(tei)
    text = pdf.with_suffix(".txt").read_text(encoding="utf-8")
    return study.title, study.abstract or "", text, text


def _step_extract(study_id: int) -> None:
    """Research question, method, key results, scope, and Contributions."""
    title, abstract, body, _ = _paper_text(study_id)
    if not body.strip():
        raise ValueError("no text could be read from this PDF")
    fields = paper_extract.extract_fields(title, abstract, body)
    research_store.apply_fields(
        study_id,
        research_question=fields.research_question,
        method=fields.method,
        key_results=fields.key_results,
        scope=fields.scope,
    )
    reextract.merge_claims(study_id, "contribution", [(text, None) for text in fields.contributions])


def _step_limitations(study_id: int) -> None:
    """The paper's own Limitations, each backed by a verified quote."""
    _, _, body, text = _paper_text(study_id)
    limitations = paper_extract.extract_limitations(body, text)
    reextract.merge_claims(study_id, "limitation", [(item.text, item.quote) for item in limitations])
    research_store.mark_extracted(study_id, ollama_model())
    # The Extraction is complete: make it askable.
    research_ask.reindex_quietly(study_id)


def _paper_sections(study_id: int) -> list[tuple[str, str]]:
    tei_file = research_store.pdf_path(study_id).with_suffix(".tei.xml")
    if not tei_file.exists():
        return []
    return [(s.head, s.text) for s in parse_tei(tei_file.read_text(encoding="utf-8")).sections]


def _step_parents(study_id: int) -> None:
    """Score how much the Paper builds on each Reference; the best become its Parent Papers."""
    title, abstract, body, _ = _paper_text(study_id)
    study = research_store.get_study(study_id)
    signals = s2.reference_signals(study.doi if study else None)
    candidates = []
    for row in research_store.reference_candidates(study_id):
        signal = signals.get(f"doi:{openalex.normalize_doi(row['doi'])}") if row["doi"] else None
        signal = signal or signals.get(f"title:{paper_extract.normalize(row['title'])}")
        influential, intents = signal if signal else (False, [])
        candidates.append(
            paper_parents.Candidate(
                study_id=int(row["id"]),
                title=row["title"],
                year=row["year"],
                mention_count=int(row["mention_count"]),
                contexts=json.loads(row["contexts_json"] or "[]"),
                influential=influential,
                intents=intents,
            )
        )
    judgements = paper_parents.choose_parents(
        title, abstract, candidates, _paper_sections(study_id), body
    )
    research_store.apply_parent_judgements(
        study_id, {sid: (j.score, j.reason) for sid, j in judgements.items()}
    )
    # New Parents move this Paper's Leads, and the Leads of every Paper that cites or lists it.
    research_store.request_leads(study_id, with_dependents=True)
    resolver.notify()


STEPS: tuple[tuple[str, Callable[[int], None]], ...] = (
    ("parse", _step_parse),
    ("extract", _step_extract),
    ("limitations", _step_limitations),
    ("parents", _step_parents),
)
FIRST_STEP = STEPS[0][0]


def _steps_from(step: str) -> list[tuple[str, Callable[[int], None]]]:
    names = [name for name, _ in STEPS]
    start = names.index(step) if step in names else 0
    return list(STEPS[start:])


def process_next_job() -> bool:
    """Run the oldest queued job from its recorded step. Returns False when the queue is empty."""
    claimed = research_store.claim_next_job()
    if claimed is None:
        return False
    job_id, study_id, step = claimed
    remaining = _steps_from(step)
    for index, (name, run) in enumerate(remaining):
        try:
            run(study_id)
        except Exception as exc:  # noqa: BLE001 — any step failure is recorded for retry
            log.exception("research job %s failed at %s", job_id, name)
            research_store.fail_job(job_id, f"{name}: {exc}")
            return True
        if index + 1 < len(remaining):
            research_store.advance_job(job_id, remaining[index + 1][0])
    research_store.finish_job(job_id)
    return True


def process_next_resolution() -> bool:
    """Network work, one item per call: resolve the next Paper against OpenAlex, else
    recompute the next Paper's Siblings and Ancestors. Returns False when nothing is due."""
    due = research_store.papers_to_resolve()
    if not due:
        return _process_next_leads()
    paper_id = due[0]
    api = scholarly.api_enabled()
    # With the API on, OpenAlex's title fills in before any fuzzy suggestion is made.
    scholarly.settle_locally(paper_id, suggest=not api)
    if not api:
        research_store.set_resolve_status(paper_id, "off")
        return True
    research_store.set_resolve_status(paper_id, "running")
    try:
        scholarly.resolve_paper(paper_id)
    except BudgetExhausted as exc:
        research_store.set_resolve_status(
            paper_id, "waiting_budget", after=exc.reset_at.isoformat()
        )
        return True
    except Exception as exc:  # noqa: BLE001 — recorded for a manual retry
        log.exception("resolving study %s failed", paper_id)
        research_store.set_resolve_status(paper_id, "failed", error=str(exc)[:500])
        return True
    research_store.set_resolve_status(paper_id, "done")
    return True


def _process_next_leads() -> bool:
    due = research_store.papers_needing_leads()
    if not due:
        return False
    paper_id = due[0]
    research_store.set_leads_status(paper_id, "running")
    try:
        paper_leads.compute_leads(paper_id)
    except BudgetExhausted as exc:
        research_store.set_leads_status(paper_id, "waiting_budget", after=exc.reset_at.isoformat())
        return True
    except Exception as exc:  # noqa: BLE001 — recorded for a manual refresh
        log.exception("finding leads for study %s failed", paper_id)
        research_store.set_leads_status(paper_id, "failed", error=str(exc)[:500])
        return True
    research_store.set_leads_status(paper_id, "done")
    return True


def _start_resolver() -> None:
    research_store.requeue_resolution(("running",))
    research_store.requeue_leads(("running",))


class _Worker:
    """A background loop that drains one queue; `on_idle` runs once per idle stretch."""

    def __init__(
        self,
        name: str,
        process: Callable[[], bool],
        on_start: Callable[[], object],
        on_idle: Callable[[], None] | None = None,
        idle_after: float = 0.0,
    ) -> None:
        self._name = name
        self._process = process
        self._on_start = on_start
        self._on_idle = on_idle
        self._idle_after = idle_after
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._on_start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._on_idle is not None:
            self._on_idle()

    def notify(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        idle_since = time.monotonic()
        idle_handled = False
        while not self._stop.is_set():
            try:
                worked = self._process()
            except Exception:  # noqa: BLE001 — keep the worker alive
                log.exception("%s loop error", self._name)
                worked = False
            if worked:
                idle_since = time.monotonic()
                idle_handled = False
                continue
            if (
                self._on_idle is not None
                and not idle_handled
                and time.monotonic() - idle_since >= self._idle_after
            ):
                self._on_idle()
                idle_handled = True
            self._wake.wait(timeout=_POLL_SECONDS)
            self._wake.clear()


worker = _Worker(
    "research-worker",
    process_next_job,
    on_start=research_store.reset_interrupted_jobs,
    on_idle=grobid.stop_if_started,
    idle_after=GROBID_IDLE_STOP_SECONDS,
)
resolver = _Worker(
    "research-resolver",
    process_next_resolution,
    on_start=_start_resolver,
)
