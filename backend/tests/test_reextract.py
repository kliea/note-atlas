"""Research Track slice 8: re-extract a Paper without losing the user's work."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import grobid, paper_extract, reextract, research_jobs
from app.db import get_connection, init_db
from app.embed import EMBEDDING_DIM
from app.main import app
from tests.test_research import FIELDS, TEI, _pdf_bytes
from tests.test_research_ask import _bag_of_words

A = "A controlled multi-document QA benchmark."
A_NEW = "A controlled multi-document question answering QA benchmark."  # a paraphrase of A
B = "Evidence that extended context doesn't help."
C = "A positional retrieval probe for long inputs."  # new in the second run
L = paper_extract.LimitationCandidate(text="Only 2023 models were evaluated.", quote="we leave newer models")
L_NEW = paper_extract.LimitationCandidate(text="Only 2023 models were evaluated in the study.", quote="newer models")
M = paper_extract.LimitationCandidate(text="English-only question sets.", quote="all questions are in English")

RUN_1 = (replace(FIELDS, contributions=[A, B]), [L])
RUN_2 = (replace(FIELDS, contributions=[A_NEW, C], method="Vary where the answer document sits."), [L_NEW, M])


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    run = {"now": RUN_1}
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: run["now"][0])
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: run["now"][1])
    monkeypatch.setattr("app.reextract.embed_texts", _bag_of_words)
    monkeypatch.setattr("app.research_ask.embed_texts", _bag_of_words)
    monkeypatch.setattr("app.index.embed_texts", lambda texts: [[0.0] * EMBEDDING_DIM for _ in texts])
    test_client = TestClient(app)
    test_client.run = run  # type: ignore[attr-defined]
    return test_client


def _drain() -> None:
    while research_jobs.process_next_job():
        pass


def _paper(client: TestClient) -> int:
    paper_id = client.post("/research/papers", files=[("files", ("p.pdf", _pdf_bytes(), "application/pdf"))]).json()[0]["id"]
    _drain()
    return paper_id


def _claims(client: TestClient, paper_id: int) -> dict[str, dict[str, Any]]:
    return {c["text"]: c for c in client.get(f"/research/studies/{paper_id}").json()["claims"]}


def test_reextraction_keeps_the_users_work(client: TestClient) -> None:
    paper = _paper(client)
    first = client.get(f"/research/studies/{paper}").json()
    claims = _claims(client, paper)
    client.patch(f"/research/claims/{claims[A]['id']}", json={"text": "My benchmark wording."})
    sent = client.post(f"/research/claims/{claims[B]['id']}/send", json={}).json()
    note_id = next(c["sent_note_id"] for c in sent["claims"] if c["id"] == claims[B]["id"])
    client.delete(f"/research/claims/{claims[L.text]['id']}")
    mine = client.post(f"/research/studies/{paper}/claims", json={"text": "No multilingual tests."}).json()

    client.run["now"] = RUN_2  # type: ignore[attr-defined]
    queued = client.post(f"/research/studies/{paper}/reextract")
    assert queued.status_code == 200 and queued.json()["job"]["step"] == "extract"
    _drain()

    after = client.get(f"/research/studies/{paper}").json()
    by_text = {c["text"]: c for c in after["claims"]}
    # The edit persists, matched to its paraphrase in the new run, which refreshes its original.
    edited = by_text["My benchmark wording."]
    assert (edited["id"], edited["original_text"], edited["stale"]) == (claims[A]["id"], A_NEW, False)
    assert A_NEW not in by_text  # not duplicated
    # The sent Claim has no match in the new run: kept with its board link, flagged stale.
    assert (by_text[B]["stale"], by_text[B]["sent_note_id"]) == (True, note_id)
    assert client.get(f"/notes/{note_id}").json()["claim_id"] == claims[B]["id"]
    # The deleted Limitation doesn't come back, even reworded.
    assert L.text not in by_text and L_NEW.text not in by_text
    # New Claims arrive; the reader's Limitation is untouched.
    assert C in by_text and by_text[M.text]["quote"] == M.quote
    assert by_text["No multilingual tests."]["id"] == mine["id"]
    # Untouched fields are replaced, and provenance is the new run's.
    assert after["method"] == "Vary where the answer document sits."
    assert after["extraction_parser"] == "grobid-0.9.1-crf"
    assert after["extraction_model"] and after["extracted_at"] > first["extracted_at"]
    # Ask sees the new Extraction.
    conn = get_connection()
    try:
        indexed = [r[0] for r in conn.execute("SELECT text FROM research_chunks WHERE study_id = ?", (paper,))]
    finally:
        conn.close()
    assert f"Contribution: {C}" in indexed and "Method: Vary where the answer document sits." in indexed


def test_an_edited_claim_matched_again_clears_its_stale_flag(client: TestClient) -> None:
    paper = _paper(client)
    b = _claims(client, paper)[B]
    client.patch(f"/research/claims/{b['id']}", json={"text": "Longer context doesn't help, per me."})
    client.run["now"] = RUN_2  # type: ignore[attr-defined]
    client.post(f"/research/studies/{paper}/reextract")
    _drain()
    assert _claims(client, paper)["Longer context doesn't help, per me."]["stale"] is True

    client.run["now"] = RUN_1  # type: ignore[attr-defined]
    client.post(f"/research/studies/{paper}/reextract")
    _drain()
    assert _claims(client, paper)["Longer context doesn't help, per me."]["stale"] is False


def test_reextract_needs_an_extracted_idle_paper(client: TestClient) -> None:
    paper = _paper(client)
    lead = client.get(f"/research/studies/{paper}").json()["references"][0]["study_id"]
    assert client.post(f"/research/studies/{lead}/reextract").status_code == 404
    assert client.post(f"/research/studies/{paper}/reextract").status_code == 200
    assert client.post(f"/research/studies/{paper}/reextract").status_code == 409  # already queued


def test_reextract_all_queues_every_idle_extracted_paper(client: TestClient) -> None:
    first, second = _paper(client), _paper(client)
    assert client.post("/research/reextract-all").json() == {"queued": 2, "busy": 0}
    assert client.post("/research/reextract-all").json() == {"queued": 0, "busy": 2}
    _drain()
    for paper in (first, second):
        assert client.get(f"/research/studies/{paper}").json()["job"]["status"] == "done"


def test_plan_merge_matches_one_to_one_and_suppresses_tombstones() -> None:
    plan = reextract.plan_merge(
        kept=[(1, A), (2, B)],
        tombstones=[L.text],
        new_items=[(A_NEW, None), (A_NEW, None), (L_NEW.text, "q"), (C, None)],
        embed=_bag_of_words,
    )
    assert plan.matched == {1: (A_NEW, None)}
    assert plan.stale == [2]
    assert plan.suppressed == [L_NEW.text]
    assert plan.inserts == [(C, None)]


def test_keeping_a_stale_claim_clears_the_flag(client: TestClient) -> None:
    paper = _paper(client)
    b = _claims(client, paper)[B]
    client.patch(f"/research/claims/{b['id']}", json={"text": "Longer context doesn't help, per me."})
    client.run["now"] = RUN_2  # type: ignore[attr-defined]
    client.post(f"/research/studies/{paper}/reextract")
    _drain()
    assert _claims(client, paper)["Longer context doesn't help, per me."]["stale"] is True

    kept = client.post(f"/research/claims/{b['id']}/keep")
    assert kept.status_code == 200 and kept.json()["stale"] is False
    assert _claims(client, paper)["Longer context doesn't help, per me."]["stale"] is False
    client.delete(f"/research/claims/{b['id']}")
    assert client.post(f"/research/claims/{b['id']}/keep").status_code == 404
