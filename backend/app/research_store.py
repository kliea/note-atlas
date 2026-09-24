"""SQLite persistence for the Research Track: Studies, cites edges, and the job queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db import get_connection, resolve_db_path
from app.models import (
    Claim,
    PossibleMatch,
    ReferenceItem,
    ResearchJob,
    StudyDetail,
    StudySummary,
)
from app.paper_extract import normalize
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
                authors_json = ?, year = ?, doi = ?, abstract = NULLIF(?, ''),
                references_status = 'ok', extraction_parser = ?
            WHERE id = ?
            """,
            (
                parsed.title,
                json.dumps(parsed.authors),
                parsed.year,
                parsed.doi,
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


def count_waiting_for_budget() -> int:
    conn = get_connection()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM studies WHERE resolve_status = 'waiting_budget'"
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
                "extracted_at": row["extracted_at"],
                "resolve_error": row["resolve_error"],
                "possible_match": _possible_match(conn, row["possible_match_id"]),
                "claims": _claims(conn, study_id),
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


def replace_paper_claims(study_id: int, kind: str, items: list[tuple[str, str | None]]) -> None:
    """Replace the paper's untouched Claims of one kind.

    Claims the user edited or sent to the board stay. Claims the user deleted are
    tombstones: a new Claim with the same text never comes back.
    """
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
        kept = conn.execute(
            """
            SELECT COALESCE(original_text, text) AS text FROM claims
            WHERE study_id = ? AND kind = ? AND author = 'paper'
            """,
            (study_id, kind),
        ).fetchall()
        blocked = {normalize(row["text"]) for row in kept}
        order = int(
            conn.execute(
                "SELECT COALESCE(MAX(order_idx), -1) FROM claims WHERE study_id = ? AND kind = ?",
                (study_id, kind),
            ).fetchone()[0]
        )
        for text, quote in items:
            key = normalize(text)
            if not key or key in blocked:
                continue
            blocked.add(key)
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


def merge_studies(survivor_id: int, absorbed_id: int) -> None:
    """Fold a Lead into another Study: every cites edge moves to the survivor (ADR 0001)."""
    conn = get_connection()
    try:
        absorbed = conn.execute("SELECT state FROM studies WHERE id = ?", (absorbed_id,)).fetchone()
        if absorbed is None or absorbed["state"] != "lead" or survivor_id == absorbed_id:
            return
        for column, other in (("to_study_id", "from_study_id"), ("from_study_id", "to_study_id")):
            rows = conn.execute(
                f"SELECT id, {other} AS other, mention_count FROM cites WHERE {column} = ?",
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
                    conn.execute(
                        "UPDATE cites SET mention_count = MAX(mention_count, ?) WHERE id = ?",
                        (int(row["mention_count"]), int(duplicate["id"])),
                    )
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
