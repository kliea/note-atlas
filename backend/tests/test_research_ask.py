"""Research Track slice 7: Ask across Papers, over Extraction fields and Claims only."""

from __future__ import annotations

import json
import math
import re
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import grobid, paper_extract, research_ask, research_jobs
from app.db import get_connection, init_db
from app.embed import EMBEDDING_DIM
from app.main import app
from app.rag import plan_ask as board_plan_ask
from tests.test_research import FIELDS, LIMITATION, TEI, _pdf_bytes


_STOPWORDS = {"the", "and", "for", "with", "what", "which", "who", "does", "these", "they", "use", "that", "this", "were"}


def _bag_of_words(texts: Sequence[str]) -> list[list[float]]:
    """Similar when texts share content words; orthogonal when they share none."""
    vectors = []
    for text in texts:
        vector = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z0-9]{3,}", text.lower()):
            if word in _STOPWORDS:
                continue
            vector[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        vectors.append([v / norm for v in vector])
    return vectors


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    tei = {"tei": TEI}
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: tei["tei"])
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    monkeypatch.setattr("app.research_ask.embed_texts", _bag_of_words)
    monkeypatch.setattr("app.index.embed_texts", _bag_of_words)
    test_client = TestClient(app)
    test_client.tei = tei  # type: ignore[attr-defined]
    return test_client


def _paper(client: TestClient, title: str = "Lost in the Middle") -> int:
    client.tei["tei"] = TEI.replace("Lost in the Middle", title)  # type: ignore[attr-defined]
    paper_id = client.post("/research/papers", files=[("files", ("p.pdf", _pdf_bytes(), "application/pdf"))]).json()[0]["id"]
    while research_jobs.process_next_job():
        pass
    return paper_id


def _ask(client: TestClient, question: str, study_ids: list[int] | None = None) -> tuple[dict[str, Any], str]:
    response = client.post("/research/ask", json={"question": question, "study_ids": study_ids})
    assert response.status_code == 200
    meta: dict[str, Any] = {}
    answer = ""
    for block in response.text.strip().split("\n\n"):
        event, data = (line.split(": ", 1)[1] for line in block.split("\n"))
        if event == "meta":
            meta = json.loads(data)
        elif event == "token":
            answer += json.loads(data)["text"]
    return meta, answer


def _ok(_messages: Any, **_kwargs: Any) -> str:
    return json.dumps({"answer": "ok"})


def _indexed(study_id: int) -> list[str]:
    conn = get_connection()
    try:
        return [r[0] for r in conn.execute("SELECT text FROM research_chunks WHERE study_id = ? ORDER BY id", (study_id,))]
    finally:
        conn.close()


def test_extraction_is_indexed_as_fields_and_claims(client: TestClient) -> None:
    paper = _paper(client)
    entries = _indexed(paper)
    assert entries[:4] == [
        f"Research question: {FIELDS.research_question}",
        f"Method: {FIELDS.method}",
        f"Key results: {FIELDS.key_results}",
        f"Scope: {FIELDS.scope}",
    ]
    assert f"Contribution: {FIELDS.contributions[0]}" in entries
    assert f'Limitation: {LIMITATION.text}\nQuote: "{LIMITATION.quote}"' in entries
    assert len(entries) == 7  # 4 fields + 2 Contributions + 1 Limitation; no full text, no Leads


def test_shared_limitations_question_cites_real_claims(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _paper(client), _paper(client, "Needles in Haystacks")
    prompts: list[str] = []

    def generate(messages: list[dict[str, str]], **kwargs: Any) -> str:
        prompts.append(messages[1]["content"])
        assert kwargs["temperature"] == 0 and kwargs["schema"]["required"] == ["answer"]
        return json.dumps({"answer": "Both evaluate only 2023 models [1][2]."})

    monkeypatch.setattr(research_ask, "chat", generate)
    meta, answer = _ask(client, "What limitations do these papers share?", [first, second])

    assert meta["grounded"] is True
    limitations = [c for c in meta["citations"] if c["label"] == "Limitation"]
    assert {c["study_id"] for c in limitations} == {first, second}
    detail = client.get(f"/research/studies/{first}").json()
    real = {c["id"] for c in detail["claims"] if c["kind"] == "limitation"}
    assert {c["claim_id"] for c in limitations if c["study_id"] == first} == real
    assert limitations[0]["text"] == LIMITATION.text
    # Citation numbers match the numbered context blocks the model saw.
    first_cite = meta["citations"][0]
    assert f"[{first_cite['number']}] Paper: {first_cite['study_title']} | {first_cite['label']}" in prompts[0]
    assert answer == "Both evaluate only 2023 models [1][2]."


def test_off_topic_question_is_declined_without_calling_the_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = _paper(client)

    def never(_messages: Any, **_kwargs: Any) -> str:
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(research_ask, "chat", never)
    for scope in (None, [paper]):
        meta, answer = _ask(client, "Which city hosts the Olympic marathon?", scope)
        assert meta == {"grounded": False, "citations": []}
        assert answer == research_ask.DECLINE_TEXT


def test_scope_is_the_selected_papers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = _paper(client), _paper(client, "Needles in Haystacks")
    monkeypatch.setattr(research_ask, "chat", _ok)
    meta, _ = _ask(client, "Summarize these papers", [second])
    assert {c["study_id"] for c in meta["citations"]} == {second}
    whole, _ = _ask(client, "What method do they use to vary the position of the relevant document?")
    assert {c["study_id"] for c in whole["citations"]} == {first, second}


def test_claim_edits_additions_and_deletions_reach_the_index(client: TestClient) -> None:
    paper = _paper(client)
    detail = client.get(f"/research/studies/{paper}").json()
    contribution = next(c for c in detail["claims"] if c["kind"] == "contribution")

    client.patch(f"/research/claims/{contribution['id']}", json={"text": "A benchmark for retrieval position."})
    client.post(f"/research/studies/{paper}/claims", json={"text": "No multilingual evaluation."})
    client.delete(f"/research/claims/{contribution['id']}")

    entries = _indexed(paper)
    assert not any("benchmark for retrieval position" in e for e in entries)
    assert "Limitation (the reader's): No multilingual evaluation." in entries


def test_papers_extracted_before_the_index_are_indexed_on_first_ask(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = _paper(client)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM research_vec")
        conn.execute("DELETE FROM research_chunks")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(research_ask, "chat", _ok)
    meta, _ = _ask(client, "What limitations does it have?")
    assert meta["grounded"] is True
    assert len(_indexed(paper)) == 7


def test_board_ask_and_research_ask_never_cross(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = _paper(client)
    note = client.post(
        "/notes", json={"title": "Limitations of my own study", "source": "", "raw_text": "Only 2023 models were evaluated."}
    ).json()

    # Board Ask sees the board note, never the Paper's Claims.
    board = board_plan_ask("What limitations were evaluated for 2023 models?")
    assert {hit.note_id for hit in board.context_hits} == {note["id"]}

    # Research Ask sees the Paper, never the note.
    monkeypatch.setattr(research_ask, "chat", _ok)
    meta, _ = _ask(client, "What limitations were evaluated for 2023 models?")
    assert meta["citations"] and {c["study_id"] for c in meta["citations"]} == {paper}

    # Send-to-board is the one bridge: the sent Claim becomes a note board Ask can find.
    limitation = next(c for c in client.get(f"/research/studies/{paper}").json()["claims"] if c["kind"] == "limitation")
    sent = client.post(f"/research/claims/{limitation['id']}/send", json={}).json()
    sent_note = next(c["sent_note_id"] for c in sent["claims"] if c["id"] == limitation["id"])
    board = board_plan_ask("What limitations were evaluated for 2023 models?")
    assert sent_note in {hit.note_id for hit in board.context_hits}


def test_a_reply_without_an_answer_is_an_error_not_a_ramble(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = _paper(client)
    monkeypatch.setattr(research_ask, "chat", lambda *_a, **_k: "Okay, let me tackle this question...")
    response = client.post("/research/ask", json={"question": "What limitations does it have?", "study_ids": [paper]})
    assert "event: error" in response.text
    assert "let me tackle" not in response.text
