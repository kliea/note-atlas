"""SQLite persistence and schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import db_path
from app.embed import EMBEDDING_DIM
from app.models import ExtractedTopic, NoteCreate, NoteDetail, NoteSummary, Point, Tag, Topic

SCHEMA_VERSION = 2

_V1_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        source TEXT NOT NULL,
        raw_text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        order_idx INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        order_idx INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
        tag TEXT NOT NULL
    )
    """,
)

_CHUNKS_TABLE = """
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
        text TEXT NOT NULL
    )
"""


def resolve_db_path() -> Path:
    """Relative DB_PATH values are resolved from the repo root."""
    raw = Path(db_path())
    if not raw.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        raw = repo_root / raw
    return raw


def get_connection() -> sqlite3.Connection:
    path = resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _load_sqlite_vec(conn)
    return conn


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    import sqlite_vec

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def migrate(conn: sqlite3.Connection | None = None) -> None:
    """Apply pending schema versions (1 = notes, 2 = chunks + sqlite-vec)."""
    owns_connection = conn is None
    if conn is None:
        conn = get_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
        )
        applied = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
        if 1 not in applied:
            for statement in _V1_STATEMENTS:
                conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        if 2 not in applied:
            conn.execute(_CHUNKS_TABLE)
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(
                    embedding float[{EMBEDDING_DIM}] distance_metric=cosine
                )
                """
            )
            conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def init_db() -> None:
    migrate()


def create_note(payload: NoteCreate) -> NoteDetail:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO notes (title, source, raw_text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (payload.title, payload.source, payload.raw_text, created_at),
        )
        conn.commit()
        note_id = int(cursor.lastrowid)
    finally:
        conn.close()
    detail = get_note(note_id)
    if detail is None:
        raise RuntimeError("note insert succeeded but row was not readable")
    return detail


def list_notes() -> list[NoteSummary]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, title, source, created_at
            FROM notes
            ORDER BY datetime(created_at) DESC, id DESC
            """
        ).fetchall()
        return [NoteSummary.model_validate(dict(row)) for row in rows]
    finally:
        conn.close()


def replace_note_extraction(note_id: int, topics: list[ExtractedTopic]) -> None:
    """Drop any prior topics for this note and write the new extraction."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM topics WHERE note_id = ?", (note_id,))
        for order_idx, topic in enumerate(topics):
            cursor = conn.execute(
                """
                INSERT INTO topics (note_id, title, order_idx)
                VALUES (?, ?, ?)
                """,
                (note_id, topic.title, order_idx),
            )
            topic_id = int(cursor.lastrowid)
            for point_idx, text in enumerate(topic.points):
                conn.execute(
                    """
                    INSERT INTO points (topic_id, text, order_idx)
                    VALUES (?, ?, ?)
                    """,
                    (topic_id, text, point_idx),
                )
            for tag in topic.tags:
                conn.execute(
                    "INSERT INTO tags (topic_id, tag) VALUES (?, ?)",
                    (topic_id, tag),
                )
        conn.commit()
    finally:
        conn.close()


def get_note(note_id: int) -> NoteDetail | None:
    conn = get_connection()
    try:
        note_row = conn.execute(
            """
            SELECT id, title, source, raw_text, created_at
            FROM notes
            WHERE id = ?
            """,
            (note_id,),
        ).fetchone()
        if note_row is None:
            return None
        topics = _load_topics(conn, note_id)
        return NoteDetail(
            id=note_row["id"],
            title=note_row["title"],
            source=note_row["source"],
            raw_text=note_row["raw_text"],
            created_at=note_row["created_at"],
            topics=topics,
        )
    finally:
        conn.close()


def _load_topics(conn: sqlite3.Connection, note_id: int) -> list[Topic]:
    topic_rows = conn.execute(
        """
        SELECT id, note_id, title, order_idx
        FROM topics
        WHERE note_id = ?
        ORDER BY order_idx ASC, id ASC
        """,
        (note_id,),
    ).fetchall()
    topics: list[Topic] = []
    for row in topic_rows:
        topic_id = int(row["id"])
        point_rows = conn.execute(
            """
            SELECT id, topic_id, text, order_idx
            FROM points
            WHERE topic_id = ?
            ORDER BY order_idx ASC, id ASC
            """,
            (topic_id,),
        ).fetchall()
        tag_rows = conn.execute(
            """
            SELECT id, topic_id, tag
            FROM tags
            WHERE topic_id = ?
            ORDER BY id ASC
            """,
            (topic_id,),
        ).fetchall()
        topics.append(
            Topic(
                id=topic_id,
                note_id=row["note_id"],
                title=row["title"],
                order_idx=row["order_idx"],
                points=[Point.model_validate(dict(p)) for p in point_rows],
                tags=[Tag.model_validate(dict(t)) for t in tag_rows],
            )
        )
    return topics


def list_note_ids() -> list[int]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id FROM notes ORDER BY id ASC").fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


def _delete_chunks_on(conn: sqlite3.Connection, note_id: int | None) -> None:
    if note_id is None:
        ids = [int(row["id"]) for row in conn.execute("SELECT id FROM chunks")]
    else:
        ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
            )
        ]
    for chunk_id in ids:
        conn.execute("DELETE FROM chunk_vec WHERE rowid = ?", (chunk_id,))
    if note_id is None:
        conn.execute("DELETE FROM chunks")
    else:
        conn.execute("DELETE FROM chunks WHERE note_id = ?", (note_id,))


def clear_chunk_index() -> None:
    conn = get_connection()
    try:
        _delete_chunks_on(conn, None)
        conn.commit()
    finally:
        conn.close()


def delete_chunks_for_note(note_id: int) -> None:
    conn = get_connection()
    try:
        _delete_chunks_on(conn, note_id)
        conn.commit()
    finally:
        conn.close()


def replace_note_chunks(
    note_id: int, items: list[tuple[int | None, str, bytes]]
) -> int:
    """Drop a note's chunks and write new text + vector rows in one transaction."""
    conn = get_connection()
    try:
        _delete_chunks_on(conn, note_id)
        for topic_id, text, embedding in items:
            cursor = conn.execute(
                """
                INSERT INTO chunks (note_id, topic_id, text)
                VALUES (?, ?, ?)
                """,
                (note_id, topic_id, text),
            )
            chunk_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                (chunk_id, embedding),
            )
        conn.commit()
        return len(items)
    finally:
        conn.close()


def search_chunk_rows(query_blob: bytes, k: int) -> list[dict[str, object]]:
    conn = get_connection()
    try:
        matches = conn.execute(
            """
            SELECT rowid, distance
            FROM chunk_vec
            WHERE embedding MATCH ?
              AND k = ?
            ORDER BY distance
            """,
            (query_blob, k),
        ).fetchall()
        hits: list[dict[str, object]] = []
        for match in matches:
            chunk = conn.execute(
                """
                SELECT id, note_id, topic_id, text
                FROM chunks
                WHERE id = ?
                """,
                (int(match["rowid"]),),
            ).fetchone()
            if chunk is None:
                continue
            hits.append(
                {
                    "id": chunk["id"],
                    "note_id": chunk["note_id"],
                    "topic_id": chunk["topic_id"],
                    "text": chunk["text"],
                    "distance": match["distance"],
                }
            )
        return hits
    finally:
        conn.close()
