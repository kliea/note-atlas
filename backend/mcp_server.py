"""Atlas MCP server: lets Claude read your Boards and notes, ask them, and add notes.

A thin stdio bridge over the Atlas HTTP API, so the backend must be running.
It imports nothing from `app`, so any client can launch it by absolute path:

    backend/.venv/bin/python backend/mcp_server.py

ATLAS_URL overrides the backend address (default http://127.0.0.1:8888).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

ATLAS_URL = os.environ.get("ATLAS_URL", "http://127.0.0.1:8888")
# Ask runs a local LLM through Ollama, which can take a while on a cold model.
ASK_TIMEOUT = 300.0

# httpx logs every request at INFO, which floods the client's MCP log.
logging.getLogger("httpx").setLevel(logging.WARNING)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

mcp = MCPServer(
    name="atlas",
    title="Note Atlas",
    instructions=(
        "Note Atlas is the user's local knowledge base. Notes live on Boards, one domain "
        "of knowledge each. Start with list_boards, then scope search and ask to a Board. "
        "The Research Track holds the user's academic Papers (list_studies, get_study, "
        "research_ask); cite Papers by title and year. "
        "Cite notes by title. Only call create_note when the user asks you to add a note."
    ),
)

# Swapped for a TestClient in tests.
client: httpx.Client = httpx.Client(base_url=ATLAS_URL, timeout=30.0)


def _get(path: str, **params: Any) -> Any:
    response = client.get(path, params={k: v for k, v in params.items() if v is not None})
    _raise_for_status(response)
    return response.json()


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    raise ValueError(f"Atlas returned {response.status_code}: {detail}")


def _boards() -> list[dict[str, Any]]:
    try:
        return _get("/boards")
    except httpx.ConnectError as exc:
        raise ValueError(
            f"Can't reach Atlas at {ATLAS_URL}. Start the backend first "
            "(uvicorn app.main:app --port 8888 --reload)."
        ) from exc


def _board_id(board: str | None) -> int | None:
    """Resolve a Board by id, name or slug. None means every Board (or the last opened, for writes)."""
    if board is None or not board.strip():
        return None
    wanted = board.strip().lower()
    boards = _boards()
    for item in boards:
        if wanted in (str(item["id"]), item["name"].lower(), item["slug"]):
            return int(item["id"])
    names = ", ".join(item["name"] for item in boards)
    raise ValueError(f"No Board called {board!r}. Boards: {names}")


@mcp.tool(annotations=READ_ONLY)
def list_boards() -> list[dict[str, Any]]:
    """List the user's Boards: id, name, domain description, and note and Files folder counts."""
    return [
        {
            key: item[key]
            for key in ("id", "name", "slug", "description", "note_count", "folder_count", "last_opened_at")
        }
        for item in _boards()
    ]


@mcp.tool(annotations=READ_ONLY)
def list_notes(board: str | None = None) -> list[dict[str, Any]]:
    """List notes (id, title, source, created date), on one Board or on every Board.

    board: a Board's name, slug or id. Omit for every Board.
    """
    notes = _get("/notes", board_id=_board_id(board))
    return [
        {key: note.get(key) for key in ("id", "title", "source", "created_at", "board_id", "study_title")}
        for note in notes
    ]


@mcp.tool(annotations=READ_ONLY)
def get_note(note_id: int) -> dict[str, Any]:
    """Read one note in full: its raw text and the topics and points Atlas extracted from it."""
    note = _get(f"/notes/{note_id}")
    for key in ("x", "y", "z", "color", "pinned"):
        note.pop(key, None)
    return note


@mcp.tool(annotations=READ_ONLY)
def search(query: str, board: str | None = None, k: int = 8) -> list[dict[str, Any]]:
    """Semantic search over note chunks. Returns the best-matching passages with their note.

    board: a Board's name, slug or id. Omit to search every Board.
    k: how many passages to return (1-20).
    """
    board_id = _board_id(board)
    hits = _get("/search", q=query, k=max(1, min(k, 20)), board_id=board_id)
    titles = {note["id"]: note["title"] for note in _get("/notes", board_id=board_id)}
    return [
        {
            "note_id": hit["note_id"],
            "note_title": titles.get(hit["note_id"]),
            "text": hit["text"],
            "score": round(hit["score"], 3),
        }
        for hit in hits
    ]


@mcp.tool(annotations=READ_ONLY)
def ask(
    question: str,
    board: str | None = None,
    note_ids: list[int] | None = None,
    k: int = 5,
) -> dict[str, Any]:
    """Ask Atlas's own local RAG (Ollama) a question, answered from the user's notes with citations.

    Slower than search; use it when the user wants Atlas's answer, otherwise prefer search
    and reason over the passages yourself.
    board: a Board's name, slug or id. note_ids: limit to these notes.
    """
    body = {"question": question, "k": max(1, min(k, 20)), "board_id": _board_id(board), "note_ids": note_ids}
    return _stream_answer("/ask", body)


def _stream_answer(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Collect one of Atlas's server-sent Ask streams into a whole answer."""
    meta: dict[str, Any] = {}
    tokens: list[str] = []
    with client.stream("POST", path, json=body, timeout=ASK_TIMEOUT) as response:
        if not response.is_success:
            response.read()
            _raise_for_status(response)
        event = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
                if event == "meta":
                    meta = data
                elif event == "token":
                    tokens.append(data["text"])
                elif event == "error":
                    raise ValueError(f"Atlas Ask failed: {data['detail']}")
    return {
        "answer": "".join(tokens).strip(),
        "grounded": meta.get("grounded"),
        "citations": meta.get("citations", []),
    }


# Research Track: Studies are Papers (PDF uploaded and extracted) or Leads (metadata only).

# Lineage lists can run to dozens of entries; get_study keeps the top of each.
LINEAGE_LIMIT = 10


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: item.get(key) for key in keys}


@mcp.tool(annotations=READ_ONLY)
def list_studies(state: str = "paper", query: str = "") -> list[dict[str, Any]]:
    """List Research Track Studies: Papers the user uploaded, or Leads Atlas suggests reading.

    state: "paper" (default), "lead", or "all".
    query: optional text to filter by title.
    """
    if state not in ("paper", "lead", "all"):
        raise ValueError('state must be "paper", "lead" or "all"')
    studies = _get("/research/studies", state=state, q=query or None)
    return [_pick(study, ("id", "state", "title", "authors", "year", "venue", "doi")) for study in studies]


@mcp.tool(annotations=READ_ONLY)
def get_study(study_id: int, include_references: bool = False) -> dict[str, Any]:
    """Read one Study: its Extraction (research question, method, key results, scope), its
    Claims (contributions and limitations, with quotes), and its lineage (Parent Papers,
    Siblings, Ancestors).

    include_references: also return the Paper's full bibliography (can be long).
    """
    study = _get(f"/research/studies/{study_id}")
    result = _pick(
        study,
        (
            "id", "state", "title", "authors", "year", "venue", "doi", "arxiv_id", "oa_url",
            "abstract", "research_question", "method", "key_results", "scope", "reference_count",
        ),
    )
    result["claims"] = [
        _pick(claim, ("id", "kind", "author", "text", "quote", "sent_note_id")) for claim in study["claims"]
    ]
    result["parents"] = [
        _pick(item, ("study_id", "state", "title", "year", "reason"))
        for item in study["parents"]
        if item.get("is_parent")
    ]
    for kind in ("siblings", "ancestors"):
        result[kind] = [
            _pick(item, ("study_id", "state", "title", "year", "shared"))
            for item in study[kind][:LINEAGE_LIMIT]
        ]
    if include_references:
        result["references"] = [
            _pick(item, ("study_id", "state", "title", "year", "doi", "mention_count"))
            for item in study["references"]
        ]
    return result


@mcp.tool(annotations=READ_ONLY)
def research_ask(question: str, study_ids: list[int] | None = None) -> dict[str, Any]:
    """Ask Atlas's Research Ask (local LLM) a question answered from Papers' Extractions and
    Claims, with numbered citations to the Paper fields and Claims it used.

    study_ids: limit to these Papers. Omit for the whole Library.
    """
    return _stream_answer("/research/ask", {"question": question, "study_ids": study_ids or None})


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
def create_note(title: str, raw_text: str, source: str = "Claude", board: str | None = None) -> dict[str, Any]:
    """Add a note to Atlas. Atlas extracts topics from it in the background.

    Only call this when the user asks you to add a note.
    board: a Board's name, slug or id. Omit for the Board the user last opened.
    """
    payload = {"title": title, "raw_text": raw_text, "source": source, "board_id": _board_id(board)}
    response = client.post("/notes", json=payload)
    _raise_for_status(response)
    note = response.json()
    return {key: note.get(key) for key in ("id", "title", "source", "board_id", "created_at")}


if __name__ == "__main__":
    mcp.run("stdio")
