"""SQLite persistence and schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import db_path
from app.embed import EMBEDDING_DIM
from app.layout import grid_position
from app.models import (
    Connection,
    ConnectionCreate,
    ExtractStatus,
    ExtractedTopic,
    NoteCreate,
    NoteDetail,
    NotePatch,
    NoteSummary,
    Point,
    Tag,
    Topic,
)

SCHEMA_VERSION = 4

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

_CONNECTIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        to_note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'link',
        created_at TEXT NOT NULL,
        CHECK (from_note_id != to_note_id)
    )
"""

_CONNECTIONS_PAIR_INDEX = """
    CREATE UNIQUE INDEX IF NOT EXISTS connections_unordered_pair
    ON connections (MIN(from_note_id, to_note_id), MAX(from_note_id, to_note_id))
"""

_NOTE_SPATIAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("x", "REAL"),
    ("y", "REAL"),
    ("z", "INTEGER DEFAULT 0"),
    ("color", "TEXT"),
    ("kind", "TEXT DEFAULT 'typed'"),
    ("pinned", "INTEGER DEFAULT 0"),
    ("ink_json", "TEXT"),
)


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
    """Apply pending schema versions (1 notes, 2 chunks, 3 space, 4 extract_status)."""
    owns_connection = conn is None
    if conn is None:
        conn = get_connection()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
        )
        applied = _applied_versions(conn)
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
        if 3 not in applied:
            _migrate_v3(conn)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (3)")
        if 4 not in applied:
            _migrate_v4(conn)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (4)")
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def migrate_down(target_version: int, conn: sqlite3.Connection | None = None) -> None:
    """Roll schema back to target_version. v4 drops extract_status; v3 drops space."""
    if target_version < 2:
        raise ValueError("cannot roll back below schema version 2 (chunks + sqlite-vec)")
    owns_connection = conn is None
    if conn is None:
        conn = get_connection()
    try:
        applied = _applied_versions(conn)
        current = max(applied) if applied else 0
        if target_version > current:
            raise ValueError(
                f"target version {target_version} is ahead of applied {current}"
            )
        if 4 in applied and target_version < 4:
            _downgrade_v4(conn)
            conn.execute("DELETE FROM schema_migrations WHERE version = 4")
        if 3 in applied and target_version < 3:
            _downgrade_v3(conn)
            conn.execute("DELETE FROM schema_migrations WHERE version = 3")
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
    )
    return {
        int(row["version"])
        for row in conn.execute("SELECT version FROM schema_migrations")
    }


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_v3(conn: sqlite3.Connection) -> None:
    existing = _column_names(conn, "notes")
    for name, declaration in _NOTE_SPATIAL_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE notes ADD COLUMN {name} {declaration}")
    conn.execute(_CONNECTIONS_TABLE)
    conn.execute(_CONNECTIONS_PAIR_INDEX)
    rows = conn.execute("SELECT id FROM notes ORDER BY id ASC").fetchall()
    for index, row in enumerate(rows):
        x, y = grid_position(index)
        conn.execute(
            "UPDATE notes SET x = ?, y = ?, z = COALESCE(z, 0), "
            "kind = COALESCE(kind, 'typed'), pinned = COALESCE(pinned, 0) "
            "WHERE id = ?",
            (x, y, int(row["id"])),
        )


def _downgrade_v3(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS connections_unordered_pair")
    conn.execute("DROP TABLE IF EXISTS connections")
    existing = _column_names(conn, "notes")
    for name, _declaration in reversed(_NOTE_SPATIAL_COLUMNS):
        if name in existing:
            conn.execute(f"ALTER TABLE notes DROP COLUMN {name}")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    existing = _column_names(conn, "notes")
    if "extract_status" not in existing:
        conn.execute(
            "ALTER TABLE notes ADD COLUMN extract_status TEXT NOT NULL DEFAULT 'idle'"
        )


def _downgrade_v4(conn: sqlite3.Connection) -> None:
    existing = _column_names(conn, "notes")
    if "extract_status" in existing:
        conn.execute("ALTER TABLE notes DROP COLUMN extract_status")


def init_db() -> None:
    migrate()


def create_note(payload: NoteCreate) -> NoteDetail:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        index = int(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0])
        x, y = grid_position(index)
        if payload.x is not None:
            x = payload.x
        if payload.y is not None:
            y = payload.y
        cursor = conn.execute(
            """
            INSERT INTO notes (
                title, source, raw_text, created_at,
                x, y, z, color, kind, pinned, ink_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, 'typed', 0, NULL)
            """,
            (payload.title, payload.source, payload.raw_text, created_at, x, y),
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
            SELECT id, title, source, created_at, x, y, z, color, kind, pinned,
                   extract_status
            FROM notes
            ORDER BY datetime(created_at) DESC, id DESC
            """
        ).fetchall()
        return [NoteSummary.model_validate(_summary_fields(row)) for row in rows]
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
            SELECT id, title, source, raw_text, created_at,
                   x, y, z, color, kind, pinned, ink_json, extract_status
            FROM notes
            WHERE id = ?
            """,
            (note_id,),
        ).fetchone()
        if note_row is None:
            return None
        topics = _load_topics(conn, note_id)
        fields = _detail_fields(note_row)
        fields["topics"] = topics
        return NoteDetail.model_validate(fields)
    finally:
        conn.close()


def _summary_fields(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "title": row["title"],
        "source": row["source"],
        "created_at": row["created_at"],
        "x": float(row["x"]),
        "y": float(row["y"]),
        "z": int(row["z"] or 0),
        "color": row["color"],
        "kind": row["kind"] or "typed",
        "pinned": bool(row["pinned"]),
        "extract_status": row["extract_status"] or "idle",
    }


def _detail_fields(row: sqlite3.Row) -> dict[str, object]:
    fields = _summary_fields(row)
    fields["raw_text"] = row["raw_text"]
    fields["ink_json"] = row["ink_json"]
    return fields


def patch_note(note_id: int, patch: NotePatch) -> NoteDetail | None:
    """Apply a partial update. Returns None if the note is missing."""
    if get_note(note_id) is None:
        return None
    updates = patch.model_dump(exclude_unset=True)
    if updates:
        if "pinned" in updates and updates["pinned"] is not None:
            updates["pinned"] = int(bool(updates["pinned"]))
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values())
        values.append(note_id)
        conn = get_connection()
        try:
            conn.execute(
                f"UPDATE notes SET {assignments} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()
    return get_note(note_id)


def set_extract_status(note_id: int, status: ExtractStatus) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notes SET extract_status = ? WHERE id = ?",
            (status, note_id),
        )
        conn.commit()
    finally:
        conn.close()


def connected_note_ids(note_id: int) -> set[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT from_note_id, to_note_id
            FROM connections
            WHERE from_note_id = ? OR to_note_id = ?
            """,
            (note_id, note_id),
        ).fetchall()
        ids: set[int] = set()
        for row in rows:
            ids.add(int(row["from_note_id"]))
            ids.add(int(row["to_note_id"]))
        ids.discard(note_id)
        return ids
    finally:
        conn.close()


def chunk_count() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return int(row["n"] if row["n"] is not None else 0)
    finally:
        conn.close()


def delete_note(note_id: int) -> bool:
    """Remove a note, its chunks, and cascaded children. False if missing."""
    if get_note(note_id) is None:
        return False
    delete_chunks_for_note(note_id)
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def create_connection(payload: ConnectionCreate) -> Connection:
    if payload.from_note_id == payload.to_note_id:
        raise ValueError("cannot connect a note to itself")
    if get_note(payload.from_note_id) is None:
        raise KeyError(payload.from_note_id)
    if get_note(payload.to_note_id) is None:
        raise KeyError(payload.to_note_id)
    created_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO connections (from_note_id, to_note_id, kind, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (payload.from_note_id, payload.to_note_id, payload.kind, created_at),
        )
        conn.commit()
        conn_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ValueError("connection already exists") from exc
    finally:
        conn.close()
    item = get_connection_by_id(conn_id)
    if item is None:
        raise RuntimeError("connection insert succeeded but row was not readable")
    return item


def get_connection_by_id(connection_id: int) -> Connection | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, from_note_id, to_note_id, kind, created_at
            FROM connections
            WHERE id = ?
            """,
            (connection_id,),
        ).fetchone()
        if row is None:
            return None
        return Connection.model_validate(dict(row))
    finally:
        conn.close()


def list_connections() -> list[Connection]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, from_note_id, to_note_id, kind, created_at
            FROM connections
            ORDER BY id ASC
            """
        ).fetchall()
        return [Connection.model_validate(dict(row)) for row in rows]
    finally:
        conn.close()


def delete_connection(connection_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        conn.commit()
        return cursor.rowcount > 0
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
