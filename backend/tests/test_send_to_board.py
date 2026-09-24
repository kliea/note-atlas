"""Research Track slice 6: send a Claim to the board as a linked, verbatim snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import grobid, paper_extract, research_jobs
from app.db import init_db
from app.embed import EMBEDDING_DIM
from app.main import app
from tests.test_research import FIELDS, LIMITATION, TEI, _pdf_bytes


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    monkeypatch.setattr("app.index.embed_texts", lambda texts: [[0.0] * EMBEDDING_DIM for _ in texts])
    return TestClient(app)


def _paper(client: TestClient) -> dict[str, Any]:
    paper_id = client.post("/research/papers", files=[("files", ("p.pdf", _pdf_bytes(), "application/pdf"))]).json()[0]["id"]
    while research_jobs.process_next_job():
        pass
    return client.get(f"/research/studies/{paper_id}").json()


def _claim(paper: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(c for c in paper["claims"] if c["kind"] == kind)


def test_sent_claim_becomes_a_verbatim_linked_note(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    extracted: list[int] = []
    monkeypatch.setattr("app.ambient.run_extraction_job", extracted.append)
    paper = _paper(client)
    claim = _claim(paper, "contribution")

    sent = client.post(f"/research/claims/{claim['id']}/send", json={"x": 500, "y": 400})
    assert sent.status_code == 201
    note_id = _claim(sent.json(), "contribution")["sent_note_id"]
    note = client.get(f"/notes/{note_id}").json()

    assert note["title"] == claim["text"]  # verbatim, never rephrased
    assert note["raw_text"] == "From: Lost in the Middle (2023) · Contribution · paper's claim"
    assert note["source"] == "paper"
    assert (note["study_id"], note["claim_id"], note["study_title"]) == (paper["id"], claim["id"], "Lost in the Middle")
    assert (note["x"], note["y"]) == (384, 336)  # centred on the last board view, snapped to the grid
    # Topics and embedding still happen, so the note gets related-link suggestions.
    assert extracted == [note_id]

    again = client.post(f"/research/claims/{claim['id']}/send", json={})
    assert again.status_code == 409


def test_later_claims_from_the_same_paper_group_beside_the_first(client: TestClient) -> None:
    paper = _paper(client)
    contributions = [c for c in paper["claims"] if c["kind"] == "contribution"]
    limitation = _claim(paper, "limitation")
    reader = client.post(f"/research/studies/{paper['id']}/claims", json={"text": "No multilingual tests."}).json()

    notes = []
    for claim in [*contributions, limitation, reader]:
        detail = client.post(f"/research/claims/{claim['id']}/send", json={"x": 500, "y": 400}).json()
        note_id = next(c["sent_note_id"] for c in detail["claims"] if c["id"] == claim["id"])
        notes.append(client.get(f"/notes/{note_id}").json())

    assert [(n["x"], n["y"]) for n in notes] == [(384, 336), (648, 336), (912, 336), (384, 504)]
    assert notes[2]["raw_text"] == (
        f"“{LIMITATION.quote}”\n\nFrom: Lost in the Middle (2023) · Limitation · paper's claim"
    )
    assert notes[3]["raw_text"] == "From: Lost in the Middle (2023) · Limitation · your claim"


def test_first_note_without_a_known_view_uses_the_board_default(client: TestClient) -> None:
    paper = _paper(client)
    detail = client.post(f"/research/claims/{_claim(paper, 'contribution')['id']}/send", json={}).json()
    note = client.get(f"/notes/{_claim(detail, 'contribution')['sent_note_id']}").json()
    assert (note["x"], note["y"]) != (0, 0)


def test_edits_never_cross_and_deleting_the_note_allows_sending_again(client: TestClient) -> None:
    paper = _paper(client)
    claim = _claim(paper, "contribution")
    note_id = _claim(client.post(f"/research/claims/{claim['id']}/send", json={}).json(), "contribution")["sent_note_id"]

    client.patch(f"/notes/{note_id}", json={"title": "My words now"})
    client.patch(f"/research/claims/{claim['id']}", json={"text": "Edited in the reader."})
    assert client.get(f"/notes/{note_id}").json()["title"] == "My words now"
    assert _claim(client.get(f"/research/studies/{paper['id']}").json(), "contribution")["text"] == "Edited in the reader."

    assert client.delete(f"/notes/{note_id}").status_code == 204
    cleared = _claim(client.get(f"/research/studies/{paper['id']}").json(), "contribution")
    assert cleared["sent_note_id"] is None
    assert client.post(f"/research/claims/{claim['id']}/send", json={}).status_code == 201


def test_unknown_claim_is_404(client: TestClient) -> None:
    assert client.post("/research/claims/9999/send", json={}).status_code == 404
