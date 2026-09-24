"""SQLite persistence for the Research Track: Studies, cites edges, and the job queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db import get_connection, resolve_db_path
from app.models import (
    Claim,
    LeadItem,
    ParentItem,
    PossibleMatch,
    ReferenceItem,
    ResearchJob,
    StudyDetail,
    StudySummary,
)
from app.paper_parents import PARENT_THRESHOLD
from app.tei import ParsedPaper

PARSER_GROBID = "grobid-0.9.1-crf"
PARSER_TEXT_ONLY = "pypdf-text"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def papers_dir() -> Path:
    """Uploaded PDFs and their parse output live next to the database."""
    path = resolve_db_path().parent / "papers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pdf_path(study_id: int) -> Path:
    return papers_dir() / f"{study_id}.pdf"


# --- uploads -----------------------------------------------------------------


def create_paper_upload(filename: str, pdf_bytes: bytes, first_step: str) -> int:
    """Store the PDF, create its Study as a Paper, and queue its job."""
    title = Path(filename).stem or "Untitled paper"
    now = _now()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO studies (state, title, original_filename, created_at)
            VALUES ('paper', ?, ?, ?)
            """,
            (title, filename, now),
        )
        study_id = int(cursor.lastrowid)
        target = pdf_path(study_id)
        target.write_bytes(pdf_bytes)
        conn.execute(
            "UPDATE studies SET pdf_path = ? WHERE id = ?", (target.name, study_id)
        )
        conn.execute(
            """
            INSERT INTO research_jobs (study_id, status, step, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?)
            """,
            (study_id, first_step, now, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return study_id


# --- parse results -------------------------------------------------------------


def apply_parse(study_id: int, parsed: ParsedPaper) -> None:
    """Write GROBID's metadata and turn every Reference into a Lead with a cites edge."""
    conn = get_connection()
    try:
        _clear_references(conn, study_id)
        conn.execute(
            """
            UPDATE studies
            SET title = COALESCE(NULLIF(?, ''), title),
                authors_json = ?, year = ?, doi = ?, arxiv_id = COALESCE(?, arxiv_id),
                abstract = NULLIF(?, ''),
                references_status = 'ok', extraction_parser = ?
            WHERE id = ?
            """,
            (
                parsed.title,
                json.dumps(parsed.authors),
                parsed.year,
                parsed.doi,
                parsed.arxiv_id,
                parsed.abstract,
                PARSER_GROBID,
                study_id,
            ),
        )
        now = _now()
        for order_idx, ref in enumerate(parsed.references):
            title = ref.title or ref.raw or "Untitled reference"
            cursor = conn.execute(
                """
                INSERT INTO studies (
                    state, title, authors_json, year, venue, doi, arxiv_id, created_at
                )
                VALUES ('lead', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    json.dumps(ref.authors),
                    ref.year,
                    ref.venue,
                    ref.doi,
                    ref.arxiv_id,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO cites (
                    from_study_id, to_study_id, order_idx, raw_reference,
                    mention_count, contexts_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    study_id,
                    int(cursor.lastrowid),
                    order_idx,
                    ref.raw,
                    ref.mention_count,
                    json.dumps(ref.contexts),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_text_only(study_id: int) -> None:
    """GROBID was unavailable: the Paper keeps its filename title and has no References."""
    conn = get_connection()
    try:
        _clear_references(conn, study_id)
        conn.execute(
            """
            UPDATE studies SET references_status = 'unavailable', extraction_parser = ?
            WHERE id = ?
            """,
            (PARSER_TEXT_ONLY, study_id),
        )
        conn.commit()
    finally:
        conn.close()


def _clear_references(conn: sqlite3.Connection, study_id: int) -> None:
    """Drop this Paper's cites edges and any Lead no other Study cites (makes parsing re-runnable)."""
    targets = [
        int(row["to_study_id"])
        for row in conn.execute(
            "SELECT to_study_id FROM cites WHERE from_study_id = ?", (study_id,)
        )
    ]
    conn.execute("DELETE FROM cites WHERE from_study_id = ?", (study_id,))
    for target in targets:
        conn.execute(
            """
            DELETE FROM studies
            WHERE id = ? AND state = 'lead'
              AND NOT EXISTS (SELECT 1 FROM cites WHERE to_study_id = ? OR from_study_id = ?)
            """,
            (target, target, target),
        )


# --- job queue -------------------------------------------------------------------


def reset_interrupted_jobs() -> int:
    """Jobs left 'running' by a previous process resume from their recorded step."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE research_jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
            (_now(),),
        )
        conn.commit()
        return int(cursor.rowcount)
    finally:
        conn.close()


def claim_next_job() -> tuple[int, int, str] | None:
    """Mark the oldest queued job running and return (job_id, study_id, step)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, study_id, step FROM research_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE research_jobs SET status = 'running', error = NULL, updated_at = ? WHERE id = ?",
            (_now(), int(row["id"])),
        )
        conn.commit()
        return int(row["id"]), int(row["study_id"]), str(row["step"])
    finally:
        conn.close()


def _update_job(job_id: int, **fields: str | None) -> None:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE research_jobs SET {assignments}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def advance_job(job_id: int, next_step: str) -> None:
    _update_job(job_id, step=next_step)


def finish_job(job_id: int) -> None:
    _update_job(job_id, status="done", step="done")


def fail_job(job_id: int, error: str) -> None:
    _update_job(job_id, status="failed", error=error[:500])


def retry_job(study_id: int) -> bool:
    """Re-queue a failed job; it resumes from the step that failed."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE research_jobs SET status = 'queued', error = NULL, updated_at = ?
            WHERE study_id = ? AND status = 'failed'
            """,
            (_now(), study_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def has_open_jobs() -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM research_jobs WHERE status IN ('queued', 'running') LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# --- reads -----------------------------------------------------------------------


_SUMMARY_SQL = """
    SELECT s.*,
           (SELECT COUNT(*) FROM cites c WHERE c.from_study_id = s.id) AS reference_count,
           j.status AS job_status, j.step AS job_step, j.error AS job_error, j.id AS job_id
    FROM studies s
    LEFT JOIN research_jobs j
      ON j.id = (SELECT MAX(id) FROM research_jobs WHERE study_id = s.id)
"""


def _queue_positions(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        "SELECT id FROM research_jobs WHERE status = 'queued' ORDER BY id"
    ).fetchall()
    return {int(row["id"]): index + 1 for index, row in enumerate(rows)}


def _summary_fields(row: sqlite3.Row, positions: dict[int, int]) -> dict[str, object]:
    job = None
    if row["job_status"] is not None:
        job = ResearchJob(
            status=row["job_status"],
            step=row["job_step"],
            error=row["job_error"],
            queue_position=positions.get(int(row["job_id"])),
        )
    return {
        "id": int(row["id"]),
        "state": row["state"],
        "title": row["title"],
        "authors": json.loads(row["authors_json"] or "[]"),
        "year": row["year"],
        "venue": row["venue"],
        "doi": row["doi"],
        "arxiv_id": row["arxiv_id"],
        "openalex_id": row["openalex_id"],
        "oa_url": row["oa_url"],
        "reference_count": int(row["reference_count"]),
        "references_status": row["references_status"],
        "resolve_status": row["resolve_status"],
        "resolve_after": row["resolve_after"],
        "job": job,
        "created_at": row["created_at"],
    }


def list_studies(state: str = "all", query: str = "") -> list[StudySummary]:
    clauses: list[str] = []
    params: list[object] = []
    if state in ("lead", "paper"):
        clauses.append("s.state = ?")
        params.append(state)
    if query.strip():
        clauses.append("s.title LIKE ?")
        params.append(f"%{query.strip()}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_connection()
    try:
        positions = _queue_positions(conn)
        rows = conn.execute(
            f"{_SUMMARY_SQL} {where} ORDER BY s.state DESC, s.id DESC", params
        ).fetchall()
        return [StudySummary.model_validate(_summary_fields(r, positions)) for r in rows]
    finally:
        conn.close()


def _possible_match(conn: sqlite3.Connection, match_id: int | None) -> PossibleMatch | None:
    if match_id is None:
        return None
    row = conn.execute(
        "SELECT id, title, year, authors_json FROM studies WHERE id = ? AND state = 'lead'",
        (match_id,),
    ).fetchone()
    if row is None:
        return None
    return PossibleMatch(
        study_id=int(row["id"]),
        title=row["title"],
        year=row["year"],
        authors=json.loads(row["authors_json"] or "[]"),
    )


# The user's mark wins; otherwise the model's score decides. SQL twin: _IS_PARENT_SQL.
def _is_parent(mark: str | None, score: float | None) -> bool:
    return mark == "pinned" or (mark is None and score is not None and score >= PARENT_THRESHOLD)


_IS_PARENT_SQL = "(c.parent_mark = 'pinned' OR (c.parent_mark IS NULL AND c.parent_score >= ?))"


def _parents(conn: sqlite3.Connection, paper_id: int) -> list[ParentItem]:
    """Every Reference the model scored or the user marked: Parents first, then by score."""
    rows = conn.execute(
        """
        SELECT s.id, s.state, s.title, s.year, s.doi, s.arxiv_id, s.oa_url,
               c.mention_count, c.parent_score, c.parent_reason, c.parent_mark
        FROM cites c JOIN studies s ON s.id = c.to_study_id
        WHERE c.from_study_id = ? AND (c.parent_score IS NOT NULL OR c.parent_mark IS NOT NULL)
        """,
        (paper_id,),
    ).fetchall()
    items = []
    for row in rows:
        mark, score = row["parent_mark"], row["parent_score"]
        items.append(
            ParentItem(
                study_id=int(row["id"]),
                state=row["state"],
                title=row["title"],
                year=row["year"],
                doi=row["doi"],
                arxiv_id=row["arxiv_id"],
                oa_url=row["oa_url"],
                mention_count=int(row["mention_count"]),
                score=score,
                reason=row["parent_reason"],
                mark=mark,
                is_parent=_is_parent(mark, score),
            )
        )
    items.sort(key=lambda p: (not p.is_parent, p.mark != "pinned", -(p.score or 0), p.study_id))
    return items


def count_waiting_for_budget() -> int:
    conn = get_connection()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM studies "
                "WHERE resolve_status = 'waiting_budget' OR leads_status = 'waiting_budget'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def get_study(study_id: int) -> StudyDetail | None:
    conn = get_connection()
    try:
        row = conn.execute(f"{_SUMMARY_SQL} WHERE s.id = ?", (study_id,)).fetchone()
        if row is None:
            return None
        fields = _summary_fields(row, _queue_positions(conn))
        references = [
            ReferenceItem(
                study_id=int(r["id"]),
                state=r["state"],
                title=r["title"],
                authors=json.loads(r["authors_json"] or "[]"),
                year=r["year"],
                doi=r["doi"],
                arxiv_id=r["arxiv_id"],
                oa_url=r["oa_url"],
                raw_reference=r["raw_reference"],
                mention_count=int(r["mention_count"]),
            )
            for r in conn.execute(
                """
                SELECT s.*, c.raw_reference, c.mention_count
                FROM cites c JOIN studies s ON s.id = c.to_study_id
                WHERE c.from_study_id = ?
                ORDER BY c.order_idx
                """,
                (study_id,),
            )
        ]
        return StudyDetail.model_validate(
            {
                **fields,
                "abstract": row["abstract"],
                "original_filename": row["original_filename"],
                "research_question": row["research_question"],
                "method": row["method"],
                "key_results": row["key_results"],
                "scope": row["scope"],
                "extraction_model": row["extraction_model"],
                "extraction_parser": row["extraction_parser"],
                "extracted_at": row["extracted_at"],
                "resolve_error": row["resolve_error"],
                "possible_match": _possible_match(conn, row["possible_match_id"]),
                "claims": _claims(conn, study_id),
                "parents": _parents(conn, study_id),
                "siblings": _leads(conn, study_id, "sibling"),
                "ancestors": _leads(conn, study_id, "ancestor"),
                "leads_status": row["leads_status"],
                "leads_error": row["leads_error"],
                "leads_after": row["leads_after"],
                "leads_api_off": _api_off(conn),
                "references": references,
            }
        )
    finally:
        conn.close()


# --- Extraction and Claims -------------------------------------------------------


def _claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=int(row["id"]),
        kind=row["kind"],
        author=row["author"],
        text=row["text"],
        quote=row["quote"],
        edited=bool(row["edited"]),
        original_text=row["original_text"],
        stale=bool(row["stale"]),
        sent_note_id=row["sent_note_id"],
    )


def _claims(conn: sqlite3.Connection, study_id: int) -> list[Claim]:
    rows = conn.execute(
        """
        SELECT * FROM claims WHERE study_id = ? AND deleted = 0
        ORDER BY kind, author DESC, order_idx, id
        """,
        (study_id,),
    ).fetchall()
    return [_claim(row) for row in rows]


def apply_fields(
    study_id: int, *, research_question: str, method: str, key_results: str, scope: str
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE studies
            SET research_question = NULLIF(?, ''), method = NULLIF(?, ''),
                key_results = NULLIF(?, ''), scope = NULLIF(?, '')
            WHERE id = ?
            """,
            (research_question, method, key_results, scope, study_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_extracted(study_id: int, model: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE studies SET extraction_model = ?, extracted_at = ? WHERE id = ?",
            (model, _now(), study_id),
        )
        conn.commit()
    finally:
        conn.close()


def claims_for_merge(study_id: int, kind: str) -> tuple[list[tuple[int, str]], list[str]]:
    """What a new extraction run must respect: (edited or sent Claims as (id, original text),
    tombstones' original texts). Reader Claims are never part of it."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, COALESCE(original_text, text) AS original, deleted FROM claims
            WHERE study_id = ? AND kind = ? AND author = 'paper'
              AND (deleted = 1 OR edited = 1 OR sent_note_id IS NOT NULL)
            ORDER BY order_idx
            """,
            (study_id, kind),
        ).fetchall()
    finally:
        conn.close()
    kept = [(int(r["id"]), str(r["original"])) for r in rows if not r["deleted"]]
    tombstones = [str(r["original"]) for r in rows if r["deleted"]]
    return kept, tombstones


def apply_claim_merge(
    study_id: int,
    kind: str,
    matched: dict[int, tuple[str, str | None]],
    stale: list[int],
    inserts: list[tuple[str, str | None]],
) -> None:
    """One transaction: drop untouched paper Claims, refresh matched ones (the user's wording
    stays), flag unmatched ones stale, and add the rest of the new run."""
    conn = get_connection()
    try:
        conn.execute(
            """
            DELETE FROM claims
            WHERE study_id = ? AND kind = ? AND author = 'paper'
              AND edited = 0 AND deleted = 0 AND sent_note_id IS NULL
            """,
            (study_id, kind),
        )
        for claim_id, (text, quote) in matched.items():
            conn.execute(
                """
                UPDATE claims
                SET quote = ?, stale = 0,
                    original_text = CASE WHEN edited = 1 THEN ? ELSE original_text END
                WHERE id = ?
                """,
                (quote, text, claim_id),
            )
        conn.executemany("UPDATE claims SET stale = 1 WHERE id = ?", [(claim_id,) for claim_id in stale])
        order = int(
            conn.execute(
                "SELECT COALESCE(MAX(order_idx), -1) FROM claims WHERE study_id = ? AND kind = ?",
                (study_id, kind),
            ).fetchone()[0]
        )
        for text, quote in inserts:
            order += 1
            conn.execute(
                """
                INSERT INTO claims (study_id, kind, author, text, quote, order_idx)
                VALUES (?, ?, 'paper', ?, ?, ?)
                """,
                (study_id, kind, text, quote, order),
            )
        conn.commit()
    finally:
        conn.close()


def extracted_paper_ids() -> list[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM studies WHERE state = 'paper' AND extracted_at IS NOT NULL ORDER BY id"
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        conn.close()


def add_reader_claim(study_id: int, kind: str, text: str) -> Claim | None:
    conn = get_connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM studies WHERE id = ? AND state = 'paper'", (study_id,)
        ).fetchone()
        if exists is None:
            return None
        order = int(
            conn.execute(
                "SELECT COALESCE(MAX(order_idx), -1) FROM claims WHERE study_id = ? AND kind = ?",
                (study_id, kind),
            ).fetchone()[0]
        )
        cursor = conn.execute(
            """
            INSERT INTO claims (study_id, kind, author, text, order_idx)
            VALUES (?, ?, 'reader', ?, ?)
            """,
            (study_id, kind, text.strip(), order + 1),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM claims WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        return _claim(row)
    finally:
        conn.close()


def edit_claim(claim_id: int, text: str) -> Claim | None:
    """Edits keep the Claim's author; the first original text is kept."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM claims WHERE id = ? AND deleted = 0", (claim_id,)
        ).fetchone()
        if row is None:
            return None
        new_text = text.strip()
        if new_text != row["text"]:
            conn.execute(
                """
                UPDATE claims
                SET text = ?, edited = 1, original_text = COALESCE(original_text, ?)
                WHERE id = ?
                """,
                (new_text, row["text"], claim_id),
            )
            conn.commit()
        return _claim(conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone())
    finally:
        conn.close()


def delete_claim(claim_id: int) -> bool:
    """A paper's Claim becomes a tombstone so re-extraction can't bring it back; a reader's is removed."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT author FROM claims WHERE id = ? AND deleted = 0", (claim_id,)
        ).fetchone()
        if row is None:
            return False
        if row["author"] == "reader":
            conn.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
        else:
            conn.execute(
                "UPDATE claims SET deleted = 1, original_text = COALESCE(original_text, text) WHERE id = ?",
                (claim_id,),
            )
        conn.commit()
        return True
    finally:
        conn.close()


# --- settings and API cache ------------------------------------------------------


def get_setting(key: str, default: str | None = None) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM research_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default
    finally:
        conn.close()


def set_settings(values: dict[str, str]) -> None:
    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO research_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            list(values.items()),
        )
        conn.commit()
    finally:
        conn.close()


def cache_get(key: str) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT body FROM api_cache WHERE key = ?", (key,)).fetchone()
        return str(row["body"]) if row is not None else None
    finally:
        conn.close()


def cache_put(entries: dict[str, str]) -> None:
    if not entries:
        return
    now = _now()
    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO api_cache (key, body, fetched_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET body = excluded.body, fetched_at = excluded.fetched_at
            """,
            [(key, body, now) for key, body in entries.items()],
        )
        conn.commit()
    finally:
        conn.close()


# --- scholarly resolution and identity -------------------------------------------


def set_resolve_status(
    study_id: int, status: str, *, error: str | None = None, after: str | None = None
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE studies SET resolve_status = ?, resolve_error = ?, resolve_after = ? WHERE id = ?",
            (status, error, after, study_id),
        )
        conn.commit()
    finally:
        conn.close()


def papers_to_resolve() -> list[int]:
    """Papers whose parse is done and whose resolution is pending, never run, or due after a budget wait."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id FROM studies
            WHERE state = 'paper' AND references_status IS NOT NULL
              AND (resolve_status IS NULL OR resolve_status = 'pending'
                   OR (resolve_status = 'waiting_budget' AND resolve_after <= ?))
            ORDER BY id
            """,
            (_now(),),
        ).fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


def requeue_resolution(statuses: tuple[str, ...]) -> int:
    marks = ",".join("?" for _ in statuses)
    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE studies SET resolve_status = 'pending', resolve_error = NULL "
            f"WHERE state = 'paper' AND resolve_status IN ({marks})",
            statuses,
        )
        conn.commit()
        return int(cursor.rowcount)
    finally:
        conn.close()


def apply_work(
    study_id: int,
    *,
    title: str | None,
    authors: list[str],
    year: int | None,
    venue: str | None,
    doi: str | None,
    openalex_id: str | None,
    oa_url: str | None,
) -> None:
    """Fill a Study from its canonical record; empty values never erase what the PDF gave."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE studies
            SET title = COALESCE(NULLIF(?, ''), title),
                authors_json = CASE WHEN ? = '[]' THEN authors_json ELSE ? END,
                year = COALESCE(?, year),
                venue = COALESCE(?, venue),
                doi = COALESCE(?, doi),
                openalex_id = COALESCE(?, openalex_id),
                oa_url = COALESCE(?, oa_url)
            WHERE id = ?
            """,
            (
                title or "",
                json.dumps(authors),
                json.dumps(authors),
                year,
                venue,
                doi,
                openalex_id,
                oa_url,
                study_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def find_same_study(
    study_id: int, *, doi: str | None, arxiv_id: str | None, openalex_id: str | None
) -> tuple[int, str] | None:
    """Another Study sharing a strong identifier: (id, state)."""
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (("doi", doi), ("arxiv_id", arxiv_id), ("openalex_id", openalex_id)):
        if value:
            clauses.append(f"lower({column}) = lower(?)")
            params.append(value)
    if not clauses:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT id, state FROM studies WHERE id != ? AND ({' OR '.join(clauses)}) "
            "ORDER BY state DESC, id LIMIT 1",
            (study_id, *params),
        ).fetchone()
        return (int(row["id"]), str(row["state"])) if row else None
    finally:
        conn.close()


def _fold_edge(conn: sqlite3.Connection, *, into: int, absorbed: int) -> None:
    """Two edges became one: keep the higher mention count and Parent score, and the user's mark."""
    a = conn.execute(
        "SELECT mention_count, parent_score, parent_reason, parent_mark FROM cites WHERE id = ?",
        (absorbed,),
    ).fetchone()
    b = conn.execute("SELECT parent_score, parent_mark FROM cites WHERE id = ?", (into,)).fetchone()
    take_score = a["parent_score"] is not None and (
        b["parent_score"] is None or a["parent_score"] > b["parent_score"]
    )
    conn.execute(
        """
        UPDATE cites SET mention_count = MAX(mention_count, ?),
               parent_score = CASE WHEN ? THEN ? ELSE parent_score END,
               parent_reason = CASE WHEN ? THEN ? ELSE parent_reason END,
               parent_mark = COALESCE(parent_mark, ?)
        WHERE id = ?
        """,
        (
            int(a["mention_count"]),
            take_score, a["parent_score"],
            take_score, a["parent_reason"],
            a["parent_mark"],
            into,
        ),
    )


def merge_studies(survivor_id: int, absorbed_id: int) -> None:
    """Fold a Lead into another Study: every cites edge moves to the survivor (ADR 0001)."""
    conn = get_connection()
    try:
        absorbed = conn.execute("SELECT state FROM studies WHERE id = ?", (absorbed_id,)).fetchone()
        if absorbed is None or absorbed["state"] != "lead" or survivor_id == absorbed_id:
            return
        for column, other in (("to_study_id", "from_study_id"), ("from_study_id", "to_study_id")):
            rows = conn.execute(
                f"SELECT id, {other} AS other FROM cites WHERE {column} = ?",
                (absorbed_id,),
            ).fetchall()
            for row in rows:
                if int(row["other"]) == survivor_id:
                    conn.execute("DELETE FROM cites WHERE id = ?", (int(row["id"]),))
                    continue
                duplicate = conn.execute(
                    f"SELECT id FROM cites WHERE {column} = ? AND {other} = ?",
                    (survivor_id, int(row["other"])),
                ).fetchone()
                if duplicate is not None:
                    _fold_edge(conn, into=int(duplicate["id"]), absorbed=int(row["id"]))
                    conn.execute("DELETE FROM cites WHERE id = ?", (int(row["id"]),))
                else:
                    conn.execute(
                        f"UPDATE cites SET {column} = ? WHERE id = ?", (survivor_id, int(row["id"]))
                    )
        conn.execute(
            "UPDATE OR IGNORE lead_dismissals SET study_id = ? WHERE study_id = ?",
            (survivor_id, absorbed_id),
        )
        conn.execute(
            "UPDATE OR IGNORE paper_leads SET study_id = ? WHERE study_id = ?",
            (survivor_id, absorbed_id),
        )
        conn.execute(
            "DELETE FROM paper_leads WHERE study_id = ? OR (paper_id = ? AND study_id = ?)",
            (absorbed_id, survivor_id, survivor_id),
        )
        # A Lead that became a Paper changes the Lineage of every Paper that knew it.
        _request_leads(conn, _dependents(conn, survivor_id))
        conn.execute(
            "UPDATE studies SET possible_match_id = NULL WHERE possible_match_id = ?", (absorbed_id,)
        )
        conn.execute("DELETE FROM studies WHERE id = ?", (absorbed_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def leads_like(study_id: int) -> list[sqlite3.Row]:
    """Leads that could be the same work as this Paper (compared by title in Python).

    A Paper's own References are excluded: a Paper can't be something it cites.
    """
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT id, title, year FROM studies
            WHERE state = 'lead' AND id != ?
              AND id NOT IN (SELECT study_id FROM identity_rejections WHERE paper_id = ?)
              AND id NOT IN (SELECT to_study_id FROM cites WHERE from_study_id = ?)
            """,
            (study_id, study_id, study_id),
        ).fetchall()
    finally:
        conn.close()


def reject_match(paper_id: int, lead_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO identity_rejections (paper_id, study_id) VALUES (?, ?)",
            (paper_id, lead_id),
        )
        conn.execute("UPDATE studies SET possible_match_id = NULL WHERE id = ?", (paper_id,))
        conn.commit()
    finally:
        conn.close()


def set_possible_match(study_id: int, match_id: int | None) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE studies SET possible_match_id = ? WHERE id = ?", (match_id, study_id))
        conn.commit()
    finally:
        conn.close()


def reference_rows(paper_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT s.id, s.title, s.year, s.doi, s.arxiv_id, s.openalex_id, s.authors_json, s.state
            FROM cites c JOIN studies s ON s.id = c.to_study_id
            WHERE c.from_study_id = ?
            ORDER BY c.order_idx
            """,
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()


def study_row(study_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    try:
        return conn.execute("SELECT * FROM studies WHERE id = ?", (study_id,)).fetchone()
    finally:
        conn.close()


# --- Parent Papers -----------------------------------------------------------------


def reference_candidates(paper_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT s.id, s.title, s.year, s.doi, c.mention_count, c.contexts_json
            FROM cites c JOIN studies s ON s.id = c.to_study_id
            WHERE c.from_study_id = ?
            ORDER BY c.order_idx
            """,
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()


def apply_parent_judgements(paper_id: int, judgements: dict[int, tuple[float, str]]) -> None:
    """Replace the model's Parent scores for this Paper. The user's marks are never touched."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE cites SET parent_score = NULL, parent_reason = NULL WHERE from_study_id = ?",
            (paper_id,),
        )
        conn.executemany(
            """
            UPDATE cites SET parent_score = ?, parent_reason = ?
            WHERE from_study_id = ? AND to_study_id = ?
            """,
            [(score, reason, paper_id, study_id) for study_id, (score, reason) in judgements.items()],
        )
        conn.commit()
    finally:
        conn.close()


def set_parent_mark(paper_id: int, study_id: int, mark: str | None) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE cites SET parent_mark = ? WHERE from_study_id = ? AND to_study_id = ?",
            (mark, paper_id, study_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def queue_step(study_id: int, step: str) -> bool:
    """Queue a job that re-runs the pipeline from `step`, unless one is already open."""
    now = _now()
    conn = get_connection()
    try:
        busy = conn.execute(
            "SELECT 1 FROM research_jobs WHERE study_id = ? AND status IN ('queued', 'running')",
            (study_id,),
        ).fetchone()
        if busy is not None:
            return False
        conn.execute(
            """
            INSERT INTO research_jobs (study_id, status, step, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?)
            """,
            (study_id, step, now, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# --- Siblings and Ancestors ----------------------------------------------------------


def _api_off(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM research_settings WHERE key = 'scholarly_api'").fetchone()
    return row is not None and row["value"] == "off"


def _leads(conn: sqlite3.Connection, paper_id: int, kind: str) -> list[LeadItem]:
    """This Paper's ranked Siblings or Ancestors; dismissed ones are hidden immediately."""
    rows = conn.execute(
        """
        SELECT s.id, s.state, s.title, s.year, s.doi, s.arxiv_id, s.oa_url,
               l.kind, l.hop, l.shared, l.similarity, l.fwci, l.via_json
        FROM paper_leads l JOIN studies s ON s.id = l.study_id
        WHERE l.paper_id = ? AND l.kind = ?
          AND l.study_id NOT IN (SELECT study_id FROM lead_dismissals WHERE paper_id = ?)
        ORDER BY l.hop, l.rank
        """,
        (paper_id, kind, paper_id),
    ).fetchall()
    return [
        LeadItem(
            study_id=int(r["id"]),
            state=r["state"],
            title=r["title"],
            year=r["year"],
            doi=r["doi"],
            arxiv_id=r["arxiv_id"],
            oa_url=r["oa_url"],
            kind=r["kind"],
            hop=int(r["hop"]),
            shared=int(r["shared"]),
            similarity=r["similarity"],
            fwci=r["fwci"],
            via=json.loads(r["via_json"] or "[]"),
        )
        for r in rows
    ]


def parent_ids(paper_id: int) -> list[int]:
    """The Studies this Paper counts as its Parents (user marks, then the model's threshold)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT c.to_study_id FROM cites c WHERE c.from_study_id = ? AND {_IS_PARENT_SQL} "
            "ORDER BY c.parent_mark IS NULL, c.parent_score DESC, c.to_study_id",
            (paper_id, PARENT_THRESHOLD),
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        conn.close()


def has_parent_judgements(paper_id: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM cites WHERE from_study_id = ? "
            "AND (parent_score IS NOT NULL OR parent_mark IS NOT NULL) LIMIT 1",
            (paper_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def reference_ids(paper_id: int) -> set[int]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT to_study_id FROM cites WHERE from_study_id = ?", (paper_id,))
        return {int(r[0]) for r in rows}
    finally:
        conn.close()


def studies_by_id(ids: list[int] | set[int]) -> dict[int, sqlite3.Row]:
    if not ids:
        return {}
    conn = get_connection()
    try:
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT * FROM studies WHERE id IN ({marks})", list(ids)).fetchall()
        return {int(r["id"]): r for r in rows}
    finally:
        conn.close()


def _aliases(conn: sqlite3.Connection, study_ids: list[int]) -> dict[int, int]:
    """{Study id: which of these it is the same work as}, matching on DOI, arXiv id, or OpenAlex
    id. Two Papers' reference lists name one work as separate Leads until resolution merges
    them, and with the API off it never does."""
    marks = ",".join("?" for _ in study_ids)
    rows = conn.execute(
        f"""
        SELECT a.id AS given, b.id AS alias
        FROM studies a JOIN studies b
          ON b.id = a.id OR lower(b.doi) = lower(a.doi)
             OR lower(b.arxiv_id) = lower(a.arxiv_id) OR b.openalex_id = a.openalex_id
        WHERE a.id IN ({marks})
        """,
        list(study_ids),
    ).fetchall()
    return {int(r["alias"]): int(r["given"]) for r in rows}


def papers_citing(study_ids: list[int]) -> dict[int, set[int]]:
    """{Library Paper id: which of these Studies its own reference list cites}."""
    if not study_ids:
        return {}
    conn = get_connection()
    try:
        aliases = _aliases(conn, study_ids)
        marks = ",".join("?" for _ in aliases)
        rows = conn.execute(
            f"""
            SELECT c.from_study_id, c.to_study_id
            FROM cites c JOIN studies s ON s.id = c.from_study_id
            WHERE s.state = 'paper' AND c.to_study_id IN ({marks})
            """,
            list(aliases),
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, set[int]] = {}
    for row in rows:
        out.setdefault(int(row[0]), set()).add(aliases[int(row[1])])
    return out


def create_lead(
    *,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None,
    doi: str | None,
    openalex_id: str | None,
    oa_url: str | None,
    abstract: str | None,
) -> int:
    """A Lead found through the scholarly API rather than a reference list."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO studies (
                state, title, authors_json, year, venue, doi, openalex_id, oa_url, abstract,
                created_at
            )
            VALUES ('lead', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, json.dumps(authors), year, venue, doi, openalex_id, oa_url, abstract, _now()),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def dismissed_ids(paper_id: int) -> set[int]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT study_id FROM lead_dismissals WHERE paper_id = ?", (paper_id,))
        return {int(r[0]) for r in rows}
    finally:
        conn.close()


def set_dismissed(paper_id: int, study_id: int, dismissed: bool) -> bool:
    """Hide a Sibling or Ancestor from this Paper for good (or bring it back)."""
    if paper_id == study_id:
        return False
    conn = get_connection()
    try:
        found = conn.execute(
            "SELECT COUNT(*) FROM studies WHERE id IN (?, ?)", (paper_id, study_id)
        ).fetchone()[0]
        if found != 2:
            return False
        if dismissed:
            conn.execute(
                "INSERT OR IGNORE INTO lead_dismissals (paper_id, study_id) VALUES (?, ?)",
                (paper_id, study_id),
            )
        else:
            conn.execute(
                "DELETE FROM lead_dismissals WHERE paper_id = ? AND study_id = ?", (paper_id, study_id)
            )
        conn.commit()
        return True
    finally:
        conn.close()


def replace_paper_leads(paper_id: int, rows: list[dict[str, object]]) -> None:
    """Swap in a fresh ranking. Each row: study_id, kind, hop, shared, similarity, fwci, via."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM paper_leads WHERE paper_id = ?", (paper_id,))
        conn.executemany(
            """
            INSERT OR IGNORE INTO paper_leads (
                paper_id, study_id, kind, hop, rank, shared, similarity, fwci, via_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    paper_id,
                    row["study_id"],
                    row["kind"],
                    row.get("hop", 1),
                    rank,
                    row.get("shared", 0),
                    row.get("similarity"),
                    row.get("fwci"),
                    json.dumps(row.get("via", [])),
                )
                for rank, row in enumerate(rows)
            ],
        )
        conn.commit()
    finally:
        conn.close()


def set_leads_status(
    paper_id: int, status: str, *, error: str | None = None, after: str | None = None
) -> None:
    """Record a recompute's outcome. A request that arrived while it ran (status flipped back
    to 'pending') is kept, so that change is picked up by the next pass."""
    conn = get_connection()
    try:
        guard = "" if status == "running" else " AND leads_status = 'running'"
        conn.execute(
            f"UPDATE studies SET leads_status = ?, leads_error = ?, leads_after = ? WHERE id = ?{guard}",
            (status, error, after, paper_id),
        )
        conn.commit()
    finally:
        conn.close()


def _request_leads(conn: sqlite3.Connection, paper_ids: list[int]) -> None:
    if not paper_ids:
        return
    marks = ",".join("?" for _ in paper_ids)
    conn.execute(
        f"UPDATE studies SET leads_status = 'pending', leads_error = NULL, leads_after = NULL "
        f"WHERE state = 'paper' AND id IN ({marks})",
        paper_ids,
    )


def _dependents(conn: sqlite3.Connection, study_id: int) -> list[int]:
    """Papers whose Leads involve this Study: they cite it, or list it as a Sibling or Ancestor."""
    rows = conn.execute(
        """
        SELECT from_study_id FROM cites WHERE to_study_id = ?
        UNION SELECT paper_id FROM paper_leads WHERE study_id = ?
        """,
        (study_id, study_id),
    ).fetchall()
    return [int(r[0]) for r in rows if int(r[0]) != study_id]


def request_leads(paper_id: int, *, with_dependents: bool = False) -> None:
    """Queue a Leads recompute for this Paper. With dependents, also every Paper whose Leads
    involve it, and every Paper citing one of its Parents (it just became their Sibling)."""
    co_citers = list(papers_citing(parent_ids(paper_id))) if with_dependents else []
    conn = get_connection()
    try:
        ids = [paper_id] + (_dependents(conn, paper_id) + co_citers if with_dependents else [])
        _request_leads(conn, ids)
        conn.commit()
    finally:
        conn.close()


def papers_needing_leads() -> list[int]:
    """Papers due a Leads recompute whose Parents and resolution have both settled."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT s.id FROM studies s
            WHERE s.state = 'paper'
              AND (s.leads_status = 'pending'
                   OR (s.leads_status = 'waiting_budget' AND s.leads_after <= ?))
              AND COALESCE(s.resolve_status, '') IN ('done', 'off', 'failed')
              AND NOT EXISTS (
                  SELECT 1 FROM research_jobs j
                  WHERE j.study_id = s.id AND j.status IN ('queued', 'running')
              )
            ORDER BY s.id
            """,
            (_now(),),
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        conn.close()


def requeue_leads(statuses: tuple[str, ...]) -> int:
    marks = ",".join("?" for _ in statuses)
    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE studies SET leads_status = 'pending', leads_error = NULL "
            f"WHERE state = 'paper' AND leads_status IN ({marks})",
            statuses,
        )
        conn.commit()
        return int(cursor.rowcount)
    finally:
        conn.close()


# --- Send to board ---------------------------------------------------------------------

# Board card size and grid, mirrored from BoardView.tsx: a Paper's notes form a loose group.
_CARD_W, _CARD_H, _SNAP = 240, 120, 24
_GROUP_COLUMNS = 3


def _snap(value: float) -> float:
    return round(value / _SNAP) * _SNAP


def claim_for_board(claim_id: int) -> tuple[sqlite3.Row, sqlite3.Row] | None:
    """(Claim, its Paper) for a live Claim, else None."""
    conn = get_connection()
    try:
        claim = conn.execute("SELECT * FROM claims WHERE id = ? AND deleted = 0", (claim_id,)).fetchone()
        if claim is None:
            return None
        study = conn.execute("SELECT * FROM studies WHERE id = ?", (claim["study_id"],)).fetchone()
        return (claim, study) if study is not None else None
    finally:
        conn.close()


def board_note_text(claim: sqlite3.Row, study: sqlite3.Row) -> tuple[str, str]:
    """(title, body): the Claim verbatim; then its quote and an attribution line."""
    year = f" ({study['year']})" if study["year"] else ""
    kind = "Contribution" if claim["kind"] == "contribution" else "Limitation"
    whose = "paper's claim" if claim["author"] == "paper" else "your claim"
    attribution = f"From: {study['title']}{year} · {kind} · {whose}"
    quote = f"“{claim['quote']}”\n\n" if claim["quote"] else ""
    return claim["text"], f"{quote}{attribution}"


def board_position(study_id: int, centre: tuple[float, float] | None) -> tuple[float, float] | None:
    """The first note from a Paper lands at the board's last view centre; later ones fill a
    grid beside it. None means "let the board pick" (no centre known yet)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT x, y FROM notes WHERE study_id = ? ORDER BY id", (study_id,)
        ).fetchall()
    finally:
        conn.close()
    if rows:
        column, row = len(rows) % _GROUP_COLUMNS, len(rows) // _GROUP_COLUMNS
        return (
            _snap(float(rows[0]["x"]) + column * (_CARD_W + _SNAP)),
            _snap(float(rows[0]["y"]) + row * (_CARD_H + 2 * _SNAP)),
        )
    if centre is None:
        return None
    return _snap(centre[0] - _CARD_W / 2), _snap(centre[1] - _CARD_H / 2)


def link_board_note(note_id: int, study_id: int, claim_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notes SET study_id = ?, claim_id = ? WHERE id = ?", (study_id, claim_id, note_id)
        )
        conn.execute("UPDATE claims SET sent_note_id = ? WHERE id = ?", (note_id, claim_id))
        conn.commit()
    finally:
        conn.close()


def claim_study_id(claim_id: int) -> int | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT study_id FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()
