"""Baseline comparison harness for the Files pipeline (F7).

Runs a folder's questions through variants of the Files pipeline only (never Board or Research),
so results compare like with like: chunk overlap, embedding model, answer model, score
threshold, and hybrid search. By default each variant changes one thing from the lab baseline.

Nothing real is touched. Every run works on a copy of the database in `<out>/work/` and builds
each index setup (embedder × chunk size × overlap) into its own ChromaDB directory under
`<out>/chroma/`, reused while the folder's files and settings are unchanged. Questions are not
written to Chat History and conversational memory is off, so each question stands alone.

Per question and variant it records the answer, whether it was the refusal line (the whole
answer, exactly), the retrieved sources, whether an expected source (file, and optionally page)
was in the top k, and latency. It writes a CSV and a Markdown summary.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import statistics
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app import llm
from app.db import resolve_db_path
from app.files import answer, build, repo, service, store
from app.files.embed import EmbeddingError

IN_SCOPE = "in_scope"
OFF_TOPIC = "off_topic"

# Embedder name → (FILES_EMBED_PROVIDER, FILES_EMBED_MODEL).
EMBEDDERS: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("ollama", "nomic-embed-text"),
    "minilm": ("sentence-transformers", "all-MiniLM-L6-v2"),
}


@dataclass(frozen=True)
class Variant:
    name: str
    chunk_size: int = 500
    chunk_overlap: int = 0
    embedder: str = "nomic-embed-text"
    model: str = "phi3"
    threshold: float | None = None
    hybrid: bool = False

    @property
    def index_key(self) -> str:
        return f"{self.embedder}-{self.chunk_size}-{self.chunk_overlap}"

    def changes(self) -> str:
        base = BASELINE
        diffs = [
            f"overlap {self.chunk_overlap}" if self.chunk_overlap != base.chunk_overlap else "",
            f"chunks {self.chunk_size}" if self.chunk_size != base.chunk_size else "",
            f"embedder {self.embedder}" if self.embedder != base.embedder else "",
            f"model {self.model}" if self.model != base.model else "",
            f"threshold {self.threshold}" if self.threshold != base.threshold else "",
            "hybrid on" if self.hybrid != base.hybrid else "",
        ]
        return ", ".join(d for d in diffs if d) or "lab defaults"


BASELINE = Variant("baseline")

DEFAULT_VARIANTS: tuple[Variant, ...] = (
    BASELINE,
    Variant("overlap-100", chunk_overlap=100),
    Variant("minilm", embedder="minilm"),
    Variant("qwen3-4b", model="qwen3:4b"),
    Variant("threshold-0.35", threshold=0.35),
    Variant("hybrid", hybrid=True),
)


@dataclass(frozen=True)
class Question:
    text: str
    kind: str  # in_scope | off_topic
    expected_source: str | None = None
    expected_pages: tuple[int, ...] = ()


@dataclass
class Plan:
    folder: str
    questions: list[Question]
    variants: list[Variant]
    top_k: int = 3


@dataclass
class Row:
    variant: str
    question: str
    kind: str
    expected_source: str
    answer: str
    refused: bool
    refusal_in_answer: bool
    sources: list[str] = field(default_factory=list)
    hit: bool | None = None
    top_score: float | None = None  # best cosine similarity retrieved, for choosing a threshold
    retrieval_ms: float = 0.0
    answer_ms: float = 0.0
    total_ms: float = 0.0
    model: str = ""
    error: str = ""


# --- loading -----------------------------------------------------------------------


def load_plan(path: Path) -> Plan:
    """Read the question file. See lab/eval_questions.yaml for the format."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError(f"{path}: expected a mapping with a `questions` list")
    questions = [_question(item, path) for item in data["questions"]]
    variants = [_variant(item) for item in data["variants"]] if data.get("variants") else list(DEFAULT_VARIANTS)
    return Plan(folder=str(data.get("folder", "")), questions=questions, variants=variants, top_k=int(data.get("top_k", 3)))


def _question(item: Any, path: Path) -> Question:
    if not isinstance(item, dict) or not item.get("q"):
        raise ValueError(f"{path}: every question needs `q`")
    kind = str(item.get("type", IN_SCOPE))
    if kind not in (IN_SCOPE, OFF_TOPIC):
        raise ValueError(f"{path}: type must be {IN_SCOPE} or {OFF_TOPIC}, got {kind!r}")
    pages = item.get("expected_page", ())
    pages = (pages,) if isinstance(pages, int) else tuple(int(p) for p in pages)
    return Question(str(item["q"]), kind, item.get("expected_source"), pages)


def _variant(item: Any) -> Variant:
    if isinstance(item, str):
        known = {v.name: v for v in DEFAULT_VARIANTS}
        if item not in known:
            raise ValueError(f"unknown variant {item!r}; built in: {', '.join(known)}")
        return known[item]
    fields = dict(item)
    if fields.get("embedder", "nomic-embed-text") not in EMBEDDERS:
        raise ValueError(f"unknown embedder {fields['embedder']!r}; use one of {', '.join(EMBEDDERS)}")
    return Variant(**fields)


# --- running -------------------------------------------------------------------------


@contextmanager
def _env(values: dict[str, str]) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _variant_env(variant: Variant, chroma_root: Path) -> dict[str, str]:
    provider, embed_name = EMBEDDERS[variant.embedder]
    return {
        "FILES_CHUNK_SIZE": str(variant.chunk_size),
        "FILES_CHUNK_OVERLAP": str(variant.chunk_overlap),
        "FILES_EMBED_PROVIDER": provider,
        "FILES_EMBED_MODEL": embed_name,
        "FILES_CHROMA_PATH": str(chroma_root / variant.index_key),
        "FILES_SCORE_THRESHOLD": "" if variant.threshold is None else str(variant.threshold),
        "FILES_HYBRID": "1" if variant.hybrid else "0",
        "FILES_LLM_MODEL": variant.model,
        "FILES_MODEL_PICKER": "0",
    }


def _copy_database(target: Path) -> None:
    """A consistent copy of the live database, even if the app is running."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    source = sqlite3.connect(resolve_db_path())
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _resolve_folder(ref: str) -> int:
    folders = repo.list_folders()
    for folder in folders:
        if folder.name == ref or str(folder.id) == ref:
            return folder.id
    names = ", ".join(f.name for f in folders) or "none"
    raise LookupError(f"no Files folder {ref!r} (folders: {names})")


def _ensure_index(variant: Variant, folder_id: int, rebuild: bool, log: Callable[[str], None]) -> None:
    """Build this index setup for the folder unless an identical build is already there."""
    chroma_dir = Path(os.environ["FILES_CHROMA_PATH"])
    signature = {
        "chunk_size": variant.chunk_size,
        "chunk_overlap": variant.chunk_overlap,
        "embedder": variant.embedder,
        "documents": sorted((d.id, d.sha256) for d in repo.list_documents(folder_id)),
    }
    marker = chroma_dir / f"folder-{folder_id}.json"
    if not rebuild and marker.exists() and json.loads(marker.read_text()) == json.loads(json.dumps(signature)):
        log(f"  index {variant.index_key}: reused")
        return
    store.delete_folder(folder_id)
    repo.reset_folder_index(folder_id)
    started = time.perf_counter()
    summary = build.build_folder(folder_id)
    log(
        f"  index {variant.index_key}: built {summary.chunks} chunks from {summary.indexed} files"
        f" ({summary.failed} failed) in {time.perf_counter() - started:.1f}s"
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(signature))


def _warm_up(model: str) -> None:
    """Load the model before timing so the first question doesn't pay for it."""
    try:
        for _ in llm.chat_stream([{"role": "user", "content": "Reply with OK."}], model=model):
            pass
    except llm.LlmError:
        pass  # the real questions will record the error


def _hit(question: Question, chunks: list[Any]) -> bool | None:
    if question.kind != IN_SCOPE or not question.expected_source:
        return None
    wanted = question.expected_source.lower()
    return any(
        wanted in chunk.filename.lower() and (not question.expected_pages or chunk.page_start in question.expected_pages)
        for chunk in chunks
    )


def _ask(variant: Variant, question: Question, folder_id: int, top_k: int) -> Row:
    row = Row(
        variant=variant.name,
        question=question.text,
        kind=question.kind,
        expected_source=_expected_label(question),
        answer="",
        refused=False,
        refusal_in_answer=False,
        model=variant.model,
    )
    started = time.perf_counter()
    try:
        plan = service.plan_ask(question.text, [folder_id], top_k)
        retrieved = time.perf_counter()
        text = "".join(service.stream_answer(plan)).strip()
        finished = time.perf_counter()
    except (EmbeddingError, llm.LlmError) as exc:
        row.error = str(exc)
        row.total_ms = round((time.perf_counter() - started) * 1000, 1)
        return row
    row.answer = text
    row.refused = answer.is_refusal(text)
    row.refusal_in_answer = answer.REFUSAL.lower() in text.lower()
    row.sources = [f"{c.filename} · p.{c.page_start}" for c in plan.chunks]
    row.hit = _hit(question, plan.chunks)
    row.top_score = max((c.score for c in plan.chunks), default=None)
    row.retrieval_ms = round((retrieved - started) * 1000, 1)
    row.answer_ms = round((finished - retrieved) * 1000, 1)
    row.total_ms = round((finished - started) * 1000, 1)
    if not plan.calls_model:
        row.model = "none (below threshold)"
    return row


def _expected_label(question: Question) -> str:
    if not question.expected_source:
        return ""
    pages = ",".join(str(p) for p in question.expected_pages)
    return f"{question.expected_source} p.{pages}" if pages else question.expected_source


def run(
    plan: Plan,
    out_dir: Path,
    *,
    folder: str | None = None,
    rebuild: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[list[Row], Path, Path]:
    """Run every question under every variant. Returns (rows, csv path, markdown path)."""
    out_dir = out_dir.resolve()
    work_db = out_dir / "work" / "notes.db"
    chroma_root = out_dir / "chroma"
    _copy_database(work_db)
    rows: list[Row] = []
    warmed: set[str] = set()
    started_at = datetime.now()
    with _env({"DB_PATH": str(work_db), "FILES_MEMORY_TURNS": "0"}):
        folder_ref = folder or plan.folder
        if not folder_ref:
            raise ValueError("name the folder in the question file (`folder:`) or with --folder")
        folder_id = _resolve_folder(folder_ref)
        for variant in plan.variants:
            log(f"{variant.name} ({variant.changes()})")
            with _env(_variant_env(variant, chroma_root)):
                _ensure_index(variant, folder_id, rebuild, log)
                if variant.model not in warmed:
                    _warm_up(variant.model)
                    warmed.add(variant.model)
                for question in plan.questions:
                    row = _ask(variant, question, folder_id, plan.top_k)
                    rows.append(row)
                    verdict = "error" if row.error else ("refused" if row.refused else "answered")
                    hit = "" if row.hit is None else (" · hit" if row.hit else " · miss")
                    log(f"    [{verdict}{hit}] {row.total_ms / 1000:.1f}s  {question.text[:60]}")
    stamp = started_at.strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"compare-{stamp}.csv"
    md_path = out_dir / f"compare-{stamp}.md"
    write_csv(rows, csv_path)
    md_path.write_text(summary_markdown(plan, rows, folder_ref, started_at), encoding="utf-8")
    return rows, csv_path, md_path


# --- reporting ------------------------------------------------------------------------

_CSV_FIELDS = list(Row.__dataclass_fields__)


def write_csv(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            record = asdict(row)
            record["sources"] = "; ".join(row.sources)
            record["hit"] = "" if row.hit is None else row.hit
            record["top_score"] = "" if row.top_score is None else row.top_score
            writer.writerow(record)


@dataclass
class VariantSummary:
    name: str
    changes: str
    off_topic_refused: tuple[int, int]
    in_scope_answered: tuple[int, int]
    hits: tuple[int, int]
    median_total_s: float | None
    median_answer_s: float | None
    errors: int


def summarize(plan: Plan, rows: list[Row]) -> list[VariantSummary]:
    out = []
    for variant in plan.variants:
        mine = [r for r in rows if r.variant == variant.name]
        ok = [r for r in mine if not r.error]
        off = [r for r in ok if r.kind == OFF_TOPIC]
        ins = [r for r in ok if r.kind == IN_SCOPE]
        graded = [r for r in ins if r.hit is not None]
        out.append(
            VariantSummary(
                name=variant.name,
                changes=variant.changes(),
                off_topic_refused=(sum(r.refused for r in off), len(off)),
                in_scope_answered=(sum(not r.refused for r in ins), len(ins)),
                hits=(sum(bool(r.hit) for r in graded), len(graded)),
                median_total_s=round(statistics.median(r.total_ms for r in ok) / 1000, 2) if ok else None,
                median_answer_s=round(statistics.median(r.answer_ms for r in ok) / 1000, 2) if ok else None,
                errors=len(mine) - len(ok),
            )
        )
    return out


def _ratio(pair: tuple[int, int]) -> str:
    done, total = pair
    return "–" if total == 0 else f"{done}/{total} ({100 * done / total:.0f}%)"


def summary_markdown(plan: Plan, rows: list[Row], folder: str, started_at: datetime) -> str:
    n_off = sum(q.kind == OFF_TOPIC for q in plan.questions)
    n_in = len(plan.questions) - n_off
    lines = [
        "# Files pipeline comparison",
        "",
        f"Run {started_at:%Y-%m-%d %H:%M}, folder **{folder}**, top-k {plan.top_k}; "
        f"{n_in} in-scope and {n_off} off-topic questions.",
        "",
        "- **Off-topic refused**: the whole answer is exactly "
        f"`{answer.REFUSAL}` (higher is better).",
        "- **In-scope answered**: in-scope questions that did *not* get the refusal (higher is better; "
        "it doesn't check the answer is right).",
        "- **Hit@k**: in-scope questions whose expected source (file, and page where given) was among the "
        "retrieved chunks.",
        "- **Latency**: median seconds per question, embedding + search + answer; each model is warmed up "
        "first so loading it isn't counted.",
        "",
        "| Variant | Changes from baseline | Off-topic refused | In-scope answered | Hit@k | Median s (answer s) | Errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summarize(plan, rows):
        latency = "–" if s.median_total_s is None else f"{s.median_total_s} ({s.median_answer_s})"
        lines.append(
            f"| {s.name} | {s.changes} | {_ratio(s.off_topic_refused)} | {_ratio(s.in_scope_answered)} | "
            f"{_ratio(s.hits)} | {latency} | {s.errors} |"
        )
    lines += [
        "",
        "## Per question",
        "",
        "R = refused, A = answered, ✓/✗ = expected source retrieved or not, ! = error.",
        "",
        "| Question | Type | " + " | ".join(v.name for v in plan.variants) + " |",
        "|---|---|" + "---|" * len(plan.variants),
    ]
    by_key = {(r.variant, r.question): r for r in rows}
    for question in plan.questions:
        cells = []
        for variant in plan.variants:
            row = by_key.get((variant.name, question.text))
            if row is None:
                cells.append("")
            elif row.error:
                cells.append("!")
            else:
                mark = "R" if row.refused else "A"
                cells.append(mark + ("" if row.hit is None else (" ✓" if row.hit else " ✗")))
        text = question.text.replace("|", "\\|")
        lines.append(f"| {text} | {question.kind.replace('_', '-')} | " + " | ".join(cells) + " |")
    lines += _score_section(plan, rows)
    errors = [r for r in rows if r.error]
    if errors:
        lines += ["", "## Errors", ""]
        lines += [f"- {r.variant}: {r.question[:60]}: {r.error}" for r in errors]
    return "\n".join(lines) + "\n"


def _score_section(plan: Plan, rows: list[Row]) -> list[str]:
    """Best retrieval score by question type, per index setup, to help pick FILES_SCORE_THRESHOLD.

    A threshold only separates the two kinds of question if it sits above every off-topic best
    score and below every in-scope one.
    """
    lines = [
        "",
        "## Best retrieval score (for choosing a threshold)",
        "",
        "Highest cosine similarity among the retrieved chunks, per question. A threshold refuses "
        "off-topic questions without calling the model only if it's above their best score.",
        "",
        "| Index setup | In-scope best score (min – max) | Off-topic best score (min – max) | Gap |",
        "|---|---|---|---|",
    ]
    seen: set[str] = set()
    for variant in plan.variants:
        # Hybrid and threshold variants share an index with the baseline; report each index once.
        if variant.index_key in seen or variant.hybrid or variant.threshold is not None:
            continue
        seen.add(variant.index_key)
        mine = [r for r in rows if r.variant == variant.name and r.top_score is not None]
        ins = [r.top_score for r in mine if r.kind == IN_SCOPE and r.top_score is not None]
        off = [r.top_score for r in mine if r.kind == OFF_TOPIC and r.top_score is not None]
        if not ins or not off:
            continue
        gap = min(ins) - max(off)
        verdict = f"{gap:+.2f} (a threshold between {max(off):.2f} and {min(ins):.2f} separates them)" if gap > 0 else f"{gap:+.2f} (they overlap)"
        lines.append(
            f"| {variant.index_key} | {min(ins):.2f} – {max(ins):.2f} | {min(off):.2f} – {max(off):.2f} | {verdict} |"
        )
    return lines
