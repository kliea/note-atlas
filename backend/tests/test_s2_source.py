"""Semantic Scholar as a full alternative to OpenAlex: resolution, Siblings, Ancestors, switching."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import crossref, grobid, openalex, paper_extract, paper_parents, research_jobs, research_store, s2
from app.db import init_db
from app.main import app
from app.works import ApiError, BudgetExhausted
from tests.test_paper_leads import _choose
from tests.test_research import FIELDS, LIMITATION, TEI, _pdf_bytes


def _paper(pid: str, title: str, year: int, *, doi: str | None = None, arxiv: str | None = None,
           refs: list[str] | None = None, cites: int = 0) -> dict[str, Any]:
    ext = {k: v for k, v in (("DOI", doi), ("ArXiv", arxiv)) if v}
    return {
        "paperId": pid, "externalIds": ext, "title": title, "year": year,
        "authors": [{"authorId": "a1", "name": "Nelson F. Liu"}], "venue": "TACL",
        "openAccessPdf": {"url": f"https://s2.example/{pid}.pdf"}, "abstract": f"About {title}.",
        "citationCount": cites, "references": [{"paperId": r} for r in refs or []],
    }


PAPER = _paper("p100", "Lost in the Middle: How Language Models Use Long Contexts", 2023,
               doi="10.1162/tacl_a_00638", refs=["p1", "p2"])
SHARP = _paper("p1", "Sharp Nearby, Fuzzy Far Away: How Neural Language Models Use Context", 2018,
               doi="10.18653/v1/p18-1027", arxiv="1805.04623", refs=["p50", "p51"])
BOOK = _paper("p2", "Speech and Language Processing", 2009, doi="10.5555/1214993")
ATTENTION = _paper("p50", "Attention Is All You Need", 2017, cites=100_000)
LSTM = _paper("p51", "Long Short-Term Memory", 1997, refs=["p60"], cites=90_000)
BACKPROP = _paper("p60", "Learning representations by back-propagating errors", 1986)
HAYSTACK = _paper("p70", "Lost in the Haystack", 2024)
CONTEXT = _paper("p71", "How Much Context Do Models Use?", 2019)
CITATIONS = {"p1": ["p100", "p70", "p71"]}


class FakeS2:
    """Answers the request shapes Atlas makes of Semantic Scholar; records each one."""

    def __init__(self) -> None:
        self.papers = {p["paperId"]: p for p in (PAPER, SHARP, BOOK, ATTENTION, LSTM, BACKPROP, HAYSTACK, CONTEXT)}
        self.calls: list[tuple[str, str]] = []

    def _find(self, ident: str) -> dict[str, Any] | None:
        for prefix, field in (("DOI:", "DOI"), ("ARXIV:", "ArXiv")):
            if ident.startswith(prefix):
                want = ident[len(prefix):].lower()
                return next((p for p in self.papers.values() if str(p["externalIds"].get(field, "")).lower() == want), None)
        return self.papers.get(ident)

    def __call__(self, method: str, path: str, *, params: dict[str, str], body: Any = None) -> Any:
        self.calls.append((method, path))
        if path == "/paper/batch":
            return [self._find(i) for i in body["ids"]]
        if path == "/paper/search/match":
            query = params["query"].lower()
            match = next((p for p in self.papers.values() if p["title"].lower().startswith(query[:20])), None)
            return {"data": [{**match, "matchScore": 90}]} if match else None
        if path.endswith("/citations"):
            pid = path.split("/")[2]
            return {"data": [{"citingPaper": {k: v for k, v in self.papers[c].items() if k != "references"}}
                             for c in CITATIONS.get(pid, [])]}
        return None  # influence signals: none


def _no_openalex(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("OpenAlex must not be called while Semantic Scholar is the source")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setenv("S2_API_KEY", "user-key")
    init_db()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    monkeypatch.setattr(paper_parents, "choose_parents", _choose({"Lost": "Sharp"}))
    monkeypatch.setattr(
        crossref, "lookup",
        lambda title, *_: [{"doi": "10.5555/1214993", "title": "Speech and Language Processing", "year": 2009}]
        if "Speech" in title else [],
    )
    monkeypatch.setattr(openalex, "_get", _no_openalex)
    return TestClient(app)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeS2:
    fake = FakeS2()
    monkeypatch.setattr(s2, "_request", fake)
    return fake


def _settle() -> None:
    while research_jobs.process_next_job() or research_jobs.process_next_resolution():
        pass


def _upload(client: TestClient) -> int:
    paper_id = client.post("/research/papers", files=[("files", ("p.pdf", _pdf_bytes(), "application/pdf"))]).json()[0]["id"]
    _settle()
    return paper_id


def test_s2_is_offered_only_with_the_users_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    status = client.get("/research/api-status").json()
    assert (status["source"], status["sources"]) == ("openalex", ["openalex", "s2"])
    monkeypatch.setenv("S2_API_KEY", "")
    assert client.get("/research/api-status").json()["sources"] == ["openalex"]
    refused = client.put("/research/api-status", json={"source": "s2"})
    assert refused.status_code == 400 and "S2_API_KEY" in refused.json()["detail"]


def test_papers_resolve_and_find_leads_through_s2(client: TestClient, fake: FakeS2) -> None:
    switched = client.put("/research/api-status", json={"source": "s2"}).json()
    assert (switched["source"], switched["enabled"]) == ("s2", True)
    paper = client.get(f"/research/studies/{_upload(client)}").json()

    assert (paper["resolve_status"], paper["year"], paper["venue"], paper["oa_url"]) == (
        "done", 2023, "TACL", "https://s2.example/p100.pdf",
    )
    assert research_store.study_row(paper["id"])["s2_id"] == "p100"
    refs = {r["title"]: r for r in paper["references"]}
    sharp = refs["Sharp Nearby, Fuzzy Far Away: How Neural Language Models Use Context"]
    assert research_store.study_row(sharp["study_id"])["s2_id"] == "p1"
    assert research_store.study_row(sharp["study_id"])["arxiv_id"] == "1805.04623"

    # Siblings from S2 citations of the Parent; never the Paper itself.
    assert [s["title"] for s in paper["siblings"]] == ["Lost in the Haystack", "How Much Context Do Models Use?"]
    # Ancestors from the Parent's S2 references, tie broken by citation count; hop 2 from LSTM.
    assert [(a["title"], a["hop"]) for a in paper["ancestors"]] == [
        ("Attention Is All You Need", 1),
        ("Long Short-Term Memory", 1),
        ("Learning representations by back-propagating errors", 2),
    ]
    assert paper["leads_status"] == "done"


def test_switching_source_re_resolves_every_paper(client: TestClient, fake: FakeS2, monkeypatch: pytest.MonkeyPatch) -> None:
    client.put("/research/api-status", json={"enabled": False})  # resolve as "off" first
    paper_id = _upload(client)
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "off"

    client.put("/research/api-status", json={"enabled": True, "source": "s2"})
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "pending"
    _settle()
    assert research_store.study_row(paper_id)["s2_id"] == "p100"

    # Back to OpenAlex: resolution is queued again (the OpenAlex guard proves it's attempted).
    client.put("/research/api-status", json={"source": "openalex"})
    assert client.get(f"/research/studies/{paper_id}").json()["resolve_status"] == "pending"


class _Resp:
    def __init__(self, status: int, text: str = "{}") -> None:
        self.status_code = status
        self.text = text


def test_rate_limits_are_retried_then_pause_network_work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    monkeypatch.setattr(s2, "MIN_INTERVAL_SECONDS", 0.0)
    responses = [_Resp(429), _Resp(200, '{"data": []}')]
    monkeypatch.setattr(s2.httpx, "get", lambda *_a, **_k: responses.pop(0))
    monkeypatch.setenv("S2_API_KEY", "user-key")
    assert s2.search_title("Something") == []  # one 429, then success

    monkeypatch.setattr(s2.httpx, "get", lambda *_a, **_k: _Resp(429))
    with pytest.raises(BudgetExhausted) as info:
        s2.search_title("Something else")
    assert info.value.reset_at > datetime.now(info.value.reset_at.tzinfo)

    monkeypatch.setenv("S2_API_KEY", "")
    with pytest.raises(ApiError):
        s2.search_title("No key")
