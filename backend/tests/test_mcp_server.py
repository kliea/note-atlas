from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import mcp_server
from app.db import init_db, replace_note_chunks
from app.embed import EMBEDDING_DIM, serialize_embedding
from app.main import app
from app.models import Citation


def _fake_embed(texts: Sequence[str]) -> list[list[float]]:
    return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


@pytest.fixture
def atlas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setattr("app.index.embed_texts", _fake_embed)
    init_db()
    test_client = TestClient(app)
    monkeypatch.setattr(mcp_server, "client", test_client)
    return test_client


def _thesis(atlas: TestClient) -> int:
    response = atlas.post("/boards", json={"name": "Thesis", "description": "Local RAG"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_tools_are_registered_with_read_only_hints() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert set(tools) == {
        "list_boards", "list_notes", "get_note", "search", "ask", "create_note",
        "list_studies", "get_study", "research_ask",
    }
    assert tools["search"].annotations.read_only_hint is True
    assert tools["get_study"].annotations.read_only_hint is True
    assert tools["create_note"].annotations.read_only_hint is False


def test_create_note_lands_on_the_named_board_and_lists_back(atlas: TestClient) -> None:
    thesis = _thesis(atlas)
    created = mcp_server.create_note("Chunking", "Split notes by topic.", board="thesis")
    assert created["board_id"] == thesis
    mcp_server.create_note("Groceries", "Eggs.", board="General")

    assert [note["title"] for note in mcp_server.list_notes(board="Thesis")] == ["Chunking"]
    assert len(mcp_server.list_notes()) == 2
    boards = {board["name"]: board for board in mcp_server.list_boards()}
    assert boards["Thesis"]["note_count"] == 1
    assert boards["Thesis"]["description"] == "Local RAG"

    note = mcp_server.get_note(created["id"])
    assert note["raw_text"] == "Split notes by topic."
    assert "x" not in note


def test_unknown_board_names_the_real_ones(atlas: TestClient) -> None:
    _thesis(atlas)
    with pytest.raises(ValueError, match="General, Thesis"):
        mcp_server.list_notes(board="Biology")


def test_search_is_scoped_to_the_board_and_carries_titles(atlas: TestClient) -> None:
    thesis = _thesis(atlas)
    on_thesis = mcp_server.create_note("Chunking", "Split notes by topic.", board=str(thesis))
    elsewhere = mcp_server.create_note("Groceries", "Eggs.", board="General")
    blob = serialize_embedding(_fake_embed(["x"])[0])
    replace_note_chunks(on_thesis["id"], [(None, "Split notes by topic.", blob)])
    replace_note_chunks(elsewhere["id"], [(None, "Eggs.", blob)])

    hits = mcp_server.search("chunking", board="Thesis")
    assert [(hit["note_title"], hit["text"]) for hit in hits] == [("Chunking", "Split notes by topic.")]
    assert len(mcp_server.search("chunking")) == 2


def test_ask_collects_the_streamed_answer(atlas: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    thesis = _thesis(atlas)
    seen: dict[str, object] = {}
    citation = Citation(note_id=1, note_title="Chunking", topic_id=None, topic_title=None, score=0.9)

    def fake_plan(question: str, **kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        return SimpleNamespace(grounded=True, citations=[citation])

    monkeypatch.setattr("app.routers.ask.plan_ask", fake_plan)
    monkeypatch.setattr("app.routers.ask.stream_answer", lambda _plan: iter(["Split ", "by topic."]))

    result = mcp_server.ask("How do I chunk?", board="Thesis")
    assert result["answer"] == "Split by topic."
    assert result["grounded"] is True
    assert result["citations"][0]["note_title"] == "Chunking"
    assert seen["board_id"] == thesis


def test_ask_surfaces_llm_errors(atlas: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import LlmError

    def broken(*_args: object, **_kwargs: object) -> None:
        raise LlmError("Ollama is not running")

    monkeypatch.setattr("app.routers.ask.plan_ask", broken)
    with pytest.raises(ValueError, match="Ollama is not running"):
        mcp_server.ask("anything")


@pytest.fixture
def paper(atlas: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict:
    from app import grobid, paper_extract, research_jobs
    from tests.test_research import FIELDS, LIMITATION, TEI, _pdf_bytes

    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    files = [("files", ("p.pdf", _pdf_bytes(), "application/pdf"))]
    paper_id = atlas.post("/research/papers", files=files).json()[0]["id"]
    while research_jobs.process_next_job():
        pass
    return atlas.get(f"/research/studies/{paper_id}").json()


def test_list_studies_shows_papers_and_rejects_bad_states(paper: dict) -> None:
    papers = mcp_server.list_studies()
    assert [(study["id"], study["title"]) for study in papers] == [(paper["id"], "Lost in the Middle")]
    assert mcp_server.list_studies(query="nothing like this") == []
    with pytest.raises(ValueError, match="state must be"):
        mcp_server.list_studies(state="books")


def test_get_study_returns_extraction_and_claims_without_references(paper: dict) -> None:
    study = mcp_server.get_study(paper["id"])
    assert study["title"] == "Lost in the Middle"
    assert study["research_question"] == paper["research_question"]
    assert {claim["kind"] for claim in study["claims"]} == {"contribution", "limitation"}
    assert "references" not in study
    assert "job" not in study

    full = mcp_server.get_study(paper["id"], include_references=True)
    assert len(full["references"]) == len(paper["references"])


def test_get_study_names_a_missing_study(atlas: TestClient) -> None:
    with pytest.raises(ValueError, match="404"):
        mcp_server.get_study(999)


def test_research_ask_collects_the_streamed_answer(atlas: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_plan(question: str, study_ids: list[int] | None = None) -> SimpleNamespace:
        seen["study_ids"] = study_ids
        return SimpleNamespace(grounded=True, citations=[])

    monkeypatch.setattr("app.research_ask.plan_ask", fake_plan)
    monkeypatch.setattr("app.research_ask.stream_answer", lambda _plan: iter(["Mid-context ", "drops."]))

    result = mcp_server.research_ask("What gets lost?", study_ids=[7])
    assert result == {"answer": "Mid-context drops.", "grounded": True, "citations": []}
    assert seen["study_ids"] == [7]
