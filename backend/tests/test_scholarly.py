"""Research Track slice 3: OpenAlex resolution, identity, budget pauses, and the API switch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import crossref, grobid, openalex, paper_extract, research_jobs, research_store
from app.db import init_db
from app.main import app
from tests.test_research import FIELDS, LIMITATION, TEI

PAPER_DOI = "10.1162/tacl_a_00638"


def _book_upload_tei() -> str:
    """An upload with no DOI whose title is close to the book Lead (and which doesn't cite the book)."""
    start = TEI.index('<biblStruct xml:id="b1">')
    end = TEI.index("</biblStruct>", start) + len("</biblStruct>")
    return (
        (TEI[:start] + TEI[end:])
        .replace("Lost in the Middle", "Speech &amp; Language Processing")
        .replace(f'<idno type="DOI">{PAPER_DOI}</idno>', "")
        .replace('when="2023-07-06"', 'when="2009"')
    )


def _work(wid: str, title: str, year: int, doi: str | None = None, refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_year": year,
        "authorships": [{"author": {"display_name": "Nelson F. Liu"}}],
        "primary_location": {"source": {"display_name": "TACL"}},
        "best_oa_location": {"pdf_url": f"https://example.org/{wid}.pdf"},
        "open_access": {},
        "referenced_works": [f"https://openalex.org/{r}" for r in refs or []],
    }


PAPER = _work("W100", "Lost in the Middle: How Language Models Use Long Contexts", 2023, PAPER_DOI, ["W1", "W9"])
SHARP = _work("W1", "Sharp Nearby, Fuzzy Far Away: How Neural Language Models Use Context", 2018, "10.18653/v1/p18-1027")
BOOK = _work("W2", "Speech and Language Processing", 2009, "10.5555/1214993")


class FakeOpenAlex:
    """Answers the three request shapes Atlas makes; records every request it sees."""

    def __init__(self, works: list[dict[str, Any]]) -> None:
        self.works = {w["id"].rsplit("/", 1)[-1]: w for w in works}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, path: str, params: dict[str, str]) -> dict[str, Any] | None:
        self.requests.append((path, params))
        if path.startswith("/works/doi:"):
            doi = path.removeprefix("/works/doi:")
            return next((w for w in self.works.values() if openalex.normalize_doi(w["doi"]) == doi), None)
        field, _, values = params["filter"].partition(":")
        wanted = values.split("|")
        if field == "openalex_id":
            return {"results": [self.works[w] for w in wanted if w in self.works]}
        if field == "doi":
            return {"results": [w for w in self.works.values() if openalex.normalize_doi(w["doi"]) in wanted]}
        return {"results": []}  # title.search: nothing


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    return TestClient(app)


@pytest.fixture
def fake_openalex(monkeypatch: pytest.MonkeyPatch) -> FakeOpenAlex:
    fake = FakeOpenAlex([PAPER, SHARP, BOOK])
    monkeypatch.setattr(openalex, "_get", fake)
    monkeypatch.setattr(
        crossref,
        "lookup",
        lambda title, author, year: [{"doi": "10.5555/1214993", "title": "Speech and Language Processing", "year": 2009}]
        if "Speech" in title
        else [],
    )
    return fake


def _upload(client: TestClient, name: str = "p.pdf") -> int:
    study_id = client.post("/research/papers", files=[("files", (name, _pdf(), "application/pdf"))]).json()[0]["id"]
    while research_jobs.process_next_job():
        pass
    return study_id


def _resolve_all() -> None:
    while research_jobs.process_next_resolution():
        pass


# --- helpers -----------------------------------------------------------------------


def test_identifier_helpers() -> None:
    assert openalex.normalize_doi("https://doi.org/10.1162/TACL_a_00638") == PAPER_DOI
    assert openalex.arxiv_doi("2107.00396v2") == "10.48550/arxiv.2107.00396"
    assert openalex.arxiv_doi(None) is None


# --- resolution --------------------------------------------------------------------


def test_paper_and_references_resolve(client: TestClient, fake_openalex: FakeOpenAlex) -> None:
    paper_id = _upload(client)
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "pending"
    _resolve_all()

    paper = client.get(f"/research/studies/{paper_id}").json()
    assert paper["resolve_status"] == "done"
    assert (paper["year"], paper["venue"], paper["doi"]) == (2023, "TACL", PAPER_DOI)
    assert paper["authors"] == ["Nelson F. Liu"]
    assert paper["oa_url"] == "https://example.org/W100.pdf"

    sharp, book = paper["references"]
    assert sharp["title"] == SHARP["title"]  # matched through the Paper's referenced_works
    assert sharp["doi"] == "10.18653/v1/p18-1027"
    assert book["doi"] == "10.5555/1214993"  # Crossref title→DOI, then OpenAlex by DOI
    assert book["year"] == 2009


def test_only_identifiers_and_titles_leave_the_machine(client: TestClient, fake_openalex: FakeOpenAlex) -> None:
    _upload(client)
    _resolve_all()
    for path, params in fake_openalex.requests:
        assert set(params) <= {"filter", "select", "per_page"}
        assert "long contexts?" not in str(params)  # never Extraction text
        assert path.startswith("/works")


def test_reference_shared_by_two_papers_becomes_one_lead(client: TestClient, fake_openalex: FakeOpenAlex) -> None:
    first = _upload(client, "a.pdf")
    second = _upload(client, "b.pdf")
    _resolve_all()
    refs_a = client.get(f"/research/studies/{first}").json()["references"]
    refs_b = client.get(f"/research/studies/{second}").json()["references"]
    # Both uploads resolve to the same DOI; the second Paper is left as a duplicate for the user,
    # but their References merge into shared Leads.
    assert [r["study_id"] for r in refs_a] == [r["study_id"] for r in refs_b]
    assert len(client.get("/research/studies", params={"state": "lead"}).json()) == 2


def test_uploading_a_lead_merges_it_into_the_new_paper(
    client: TestClient, fake_openalex: FakeOpenAlex, monkeypatch: pytest.MonkeyPatch
) -> None:
    citing = _upload(client, "citing.pdf")
    _resolve_all()
    sharp_lead = client.get(f"/research/studies/{citing}").json()["references"][0]["study_id"]

    # Now the user uploads the Sharp paper itself: its DOI matches the Lead.
    sharp_tei = TEI.replace("Lost in the Middle", SHARP["title"]).replace(PAPER_DOI, "10.18653/v1/p18-1027")
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: sharp_tei)
    sharp_paper = _upload(client, "sharp.pdf")
    _resolve_all()

    assert client.get(f"/research/studies/{sharp_lead}").status_code == 404
    refs = client.get(f"/research/studies/{citing}").json()["references"]
    assert refs[0]["study_id"] == sharp_paper
    assert refs[0]["state"] == "paper"


def test_fuzzy_title_asks_and_remembers_the_answer(
    client: TestClient, fake_openalex: FakeOpenAlex, monkeypatch: pytest.MonkeyPatch
) -> None:
    citing = _upload(client, "citing.pdf")
    _resolve_all()
    book_lead = client.get(f"/research/studies/{citing}").json()["references"][1]["study_id"]

    no_doi = _book_upload_tei()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: no_doi)
    upload = _upload(client, "book.pdf")
    _resolve_all()
    match = client.get(f"/research/studies/{upload}").json()["possible_match"]
    assert match["study_id"] == book_lead

    no = client.post(f"/research/studies/{upload}/identity", json={"same": False}).json()
    assert no["possible_match"] is None
    client.post(f"/research/studies/{upload}/resolve")
    _resolve_all()
    assert client.get(f"/research/studies/{upload}").json()["possible_match"] is None  # not asked again


def test_confirming_a_fuzzy_match_merges(
    client: TestClient, fake_openalex: FakeOpenAlex, monkeypatch: pytest.MonkeyPatch
) -> None:
    citing = _upload(client, "citing.pdf")
    _resolve_all()
    book_lead = client.get(f"/research/studies/{citing}").json()["references"][1]["study_id"]
    no_doi = _book_upload_tei()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: no_doi)
    upload = _upload(client, "book.pdf")
    _resolve_all()
    client.post(f"/research/studies/{upload}/identity", json={"same": True})
    assert client.get(f"/research/studies/{book_lead}").status_code == 404
    assert client.get(f"/research/studies/{citing}").json()["references"][1]["study_id"] == upload


# --- budget and the API switch ------------------------------------------------------


def test_budget_exhaustion_pauses_then_resumes(client: TestClient, fake_openalex: FakeOpenAlex, monkeypatch: pytest.MonkeyPatch) -> None:
    paper_id = _upload(client)
    reset = datetime.now(timezone.utc) + timedelta(hours=6)

    def exhausted(_path: str, _params: dict[str, str]) -> None:
        raise openalex.BudgetExhausted(reset)

    monkeypatch.setattr(openalex, "_get", exhausted)
    _resolve_all()
    paper = client.get(f"/research/studies/{paper_id}").json()
    assert paper["resolve_status"] == "waiting_budget"
    assert paper["resolve_after"] == reset.isoformat()
    # Local steps were not blocked.
    assert paper["job"]["status"] == "done"
    assert paper["research_question"]
    assert research_jobs.process_next_resolution() is False  # not due yet

    research_store.set_resolve_status(
        paper_id, "waiting_budget", after=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    )
    monkeypatch.setattr(openalex, "_get", fake_openalex)
    _resolve_all()
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "done"


def test_api_off_skips_resolution_until_switched_on(client: TestClient, fake_openalex: FakeOpenAlex) -> None:
    status = client.put("/research/api-status", json={"enabled": False}).json()
    assert status["enabled"] is False
    paper_id = _upload(client)
    _resolve_all()
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "off"
    assert fake_openalex.requests == []

    client.put("/research/api-status", json={"enabled": True})
    _resolve_all()
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "done"


class _Resp:
    def __init__(self, status: int, headers: dict[str, str], body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self.headers = httpx.Headers(headers)
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


def test_budget_headers_recorded_and_429_raises(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def ok(url: str, **_kwargs: Any) -> _Resp:
        calls.append(url)
        return _Resp(
            200,
            {"x-ratelimit-remaining-usd": "0.07", "x-ratelimit-limit-usd": "0.1", "x-ratelimit-reset": "3600"},
            PAPER,
        )

    monkeypatch.setattr(openalex.httpx, "get", ok)
    assert openalex.work_by_doi(PAPER_DOI).title == PAPER["title"]
    assert openalex.work_by_doi(PAPER_DOI) is not None
    assert len(calls) == 1  # the second lookup came from the cache
    status = client.get("/research/api-status").json()
    assert (status["remaining_usd"], status["limit_usd"]) == (0.07, 0.1)

    monkeypatch.setattr(openalex.httpx, "get", lambda url, **_: _Resp(429, {"retry-after": "120"}))
    with pytest.raises(openalex.BudgetExhausted) as info:
        openalex.work_by_doi("10.1/other")
    assert timedelta(seconds=100) < info.value.reset_at - datetime.now(timezone.utc) <= timedelta(seconds=120)
    assert client.get("/research/api-status").json()["remaining_usd"] == 0.0
