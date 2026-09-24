"""Research Track slice 5: Siblings, Ancestors, dismissals, and uploading a Lead."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import crossref, grobid, openalex, paper_extract, paper_parents, research_jobs
from app.db import init_db
from app.main import app
from app.paper_parents import Candidate, ParentJudgement
from tests.test_research import FIELDS, LIMITATION, TEI
from tests.test_scholarly import BOOK, PAPER, PAPER_DOI, SHARP, FakeOpenAlex, _pdf, _work

SHARP_DOI = "10.18653/v1/p18-1027"


def _with(work: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {**work, **extra}


def _refs(*ids: str) -> list[str]:
    return [f"https://openalex.org/{i}" for i in ids]


# Sharp (this Paper's Parent) cites two works; the higher-fwci one seeds hop 2.
SHARP_W = _with(SHARP, referenced_works=_refs("W50", "W51"))
ATTENTION = _with(_work("W50", "Attention Is All You Need", 2017), fwci=2.0)
LSTM = _with(_work("W51", "Long Short-Term Memory", 1997, refs=["W60"]), fwci=5.0)
BACKPROP = _work("W60", "Learning representations by back-propagating errors", 1986)
# Works citing Sharp: two Siblings, plus this Paper itself, which must never be its own Sibling.
HAYSTACK = _work("W70", "Lost in the Haystack", 2024, refs=["W1"])
CONTEXT = _work("W71", "How Much Context Do Models Use?", 2019, refs=["W1"])
PAPER_W = _with(PAPER, referenced_works=_refs("W1", "W2"))


class LineageOpenAlex(FakeOpenAlex):
    """Also answers `cites:` (who cites these works)."""

    def __call__(self, path: str, params: dict[str, str]) -> dict[str, Any] | None:
        field, _, values = params.get("filter", "").partition(":")
        if field == "cites":
            wanted = set(values.split("|"))
            self.requests.append((path, params))
            return {
                "results": [
                    w for w in self.works.values()
                    if wanted & {r.rsplit("/", 1)[-1] for r in w["referenced_works"]}
                ]
            }
        return super().__call__(path, params)


def _choose(parents_by_paper: dict[str, str]):
    """Fake Parent selection: {paper title prefix: Parent title prefix}."""

    def choose(title: str, _abstract: str, candidates: list[Candidate], _sections: Any, _body: str):
        want = next((p for prefix, p in parents_by_paper.items() if title.startswith(prefix)), None)
        return {
            c.study_id: ParentJudgement(0.9 if want and c.title.startswith(want) else 0.2, "because")
            for c in candidates
        }

    return choose


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> LineageOpenAlex:
    fake = LineageOpenAlex([PAPER_W, SHARP_W, BOOK, ATTENTION, LSTM, BACKPROP, HAYSTACK, CONTEXT])
    monkeypatch.setattr(openalex, "_get", fake)
    monkeypatch.setattr(
        crossref,
        "lookup",
        lambda title, *_: [{"doi": "10.5555/1214993", "title": "Speech and Language Processing", "year": 2009}]
        if "Speech" in title
        else [],
    )
    return fake


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setenv("S2_API_KEY", "")
    init_db()
    tei = {"tei": TEI}
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: tei["tei"])
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    monkeypatch.setattr(paper_parents, "choose_parents", _choose({"Lost": "Sharp"}))
    test_client = TestClient(app)
    test_client.tei = tei  # type: ignore[attr-defined]
    return test_client


def _settle() -> None:
    """Drain the local job queue and the network worker (resolution, then Leads)."""
    while research_jobs.process_next_job() or research_jobs.process_next_resolution():
        pass


def _upload(client: TestClient, tei: str = TEI) -> int:
    client.tei["tei"] = tei  # type: ignore[attr-defined]
    paper_id = client.post("/research/papers", files=[("files", ("p.pdf", _pdf(), "application/pdf"))]).json()[0]["id"]
    _settle()
    return paper_id


def _titles(items: list[dict[str, Any]]) -> list[str]:
    return [item["title"] for item in items]


def test_siblings_and_ancestors_from_openalex(client: TestClient, fake: LineageOpenAlex) -> None:
    paper = client.get(f"/research/studies/{_upload(client)}").json()
    assert paper["leads_status"] == "done"
    [parent] = [p for p in paper["parents"] if p["is_parent"]]

    # Equal shared Parents and similarity: the newer Sibling first. Never the Paper itself.
    assert _titles(paper["siblings"]) == [HAYSTACK["title"], CONTEXT["title"]]
    assert all(s["state"] == "lead" and s["via"] == [parent["study_id"]] for s in paper["siblings"])
    assert paper["siblings"][0]["oa_url"] == "https://example.org/W70.pdf"

    ancestors = paper["ancestors"]
    assert [(a["title"], a["hop"]) for a in ancestors] == [
        (LSTM["title"], 1),  # higher fwci breaks the tie
        (ATTENTION["title"], 1),
        (BACKPROP["title"], 2),  # grown from the hop-1 Ancestors
    ]
    assert ancestors[0]["via"] == [parent["study_id"]]
    assert ancestors[2]["via"] == [ancestors[0]["study_id"]]
    cites_queries = [p["filter"] for _, p in fake.requests if p.get("filter", "").startswith("cites:")]
    assert cites_queries == ["cites:W1"]


def test_dismissed_leads_never_return(client: TestClient, fake: LineageOpenAlex) -> None:
    paper_id = _upload(client)
    paper = client.get(f"/research/studies/{paper_id}").json()
    haystack = paper["siblings"][0]["study_id"]
    lstm = paper["ancestors"][0]["study_id"]

    client.put(f"/research/studies/{paper_id}/leads/{haystack}", json={"dismissed": True})
    hidden = client.put(f"/research/studies/{paper_id}/leads/{lstm}", json={"dismissed": True}).json()
    assert haystack not in {s["study_id"] for s in hidden["siblings"]}
    assert lstm not in {a["study_id"] for a in hidden["ancestors"]}

    refreshed = client.post(f"/research/studies/{paper_id}/leads/refresh").json()
    assert refreshed["leads_status"] == "pending"
    _settle()
    paper = client.get(f"/research/studies/{paper_id}").json()
    assert paper["leads_status"] == "done"
    assert _titles(paper["siblings"]) == [CONTEXT["title"]]
    # LSTM is gone, so Attention alone seeds hop 2 (and cites nothing Atlas can see).
    assert _titles(paper["ancestors"]) == [ATTENTION["title"]]
    assert client.put(f"/research/studies/{paper_id}/leads/99999", json={"dismissed": True}).status_code == 404


def test_api_off_finds_siblings_only_in_the_library(client: TestClient, fake: LineageOpenAlex) -> None:
    client.put("/research/api-status", json={"enabled": False})
    first = _upload(client)
    second_tei = TEI.replace("Lost in the Middle", "Lost Again").replace(PAPER_DOI, "10.1/second")
    second = _upload(client, second_tei)

    paper = client.get(f"/research/studies/{first}").json()
    assert paper["leads_api_off"] is True
    assert paper["leads_status"] == "done"
    # Both reference lists name Sharp (same arXiv id) as separate Leads; they still count as one.
    assert [(s["study_id"], s["state"], s["shared"]) for s in paper["siblings"]] == [(second, "paper", 1)]
    assert paper["ancestors"] == []  # Sharp isn't uploaded, and the API can't see its references
    assert fake.requests == []


def test_uploading_a_lead_replaces_guessed_ancestors(
    client: TestClient, fake: LineageOpenAlex, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_id = _upload(client)
    assert _titles(client.get(f"/research/studies/{paper_id}").json()["ancestors"]) == [
        LSTM["title"], ATTENTION["title"], BACKPROP["title"],
    ]

    # The user uploads the Parent's own PDF. It cites only the textbook, which it builds on.
    start = TEI.index('<biblStruct xml:id="b0">')
    end = TEI.index("</biblStruct>", start) + len("</biblStruct>")
    sharp_tei = (TEI[:start] + TEI[end:]).replace("Lost in the Middle", "Sharp Nearby, Fuzzy Far Away").replace(
        PAPER_DOI, SHARP_DOI
    )
    monkeypatch.setattr(paper_parents, "choose_parents", _choose({"Lost": "Sharp", "Sharp": "Speech"}))
    _upload(client, sharp_tei)

    paper = client.get(f"/research/studies/{paper_id}").json()
    [parent] = [p for p in paper["parents"] if p["is_parent"]]
    assert parent["state"] == "paper"  # the Lead became a Paper, and stayed this Paper's Parent
    assert paper["leads_status"] == "done"
    # Its real Parent replaces the Ancestors guessed from its OpenAlex reference list.
    assert _titles(paper["ancestors"]) == [BOOK["title"]]
    assert paper["ancestors"][0]["via"] == [parent["study_id"]]


def _sharp_tei(header_id: str) -> str:
    """Sharp's own PDF: cites only the textbook; its header carries `header_id` in place of a DOI."""
    start = TEI.index('<biblStruct xml:id="b0">')
    end = TEI.index("</biblStruct>", start) + len("</biblStruct>")
    return (
        (TEI[:start] + TEI[end:])
        .replace("Lost in the Middle", "Sharp Nearby, Fuzzy Far Away")
        .replace(f'<idno type="DOI">{PAPER_DOI}</idno>', header_id)
        .replace('when="2023-07-06"', 'when="2018"')
    )


def test_api_off_upload_of_a_lead_merges_on_its_arxiv_id(
    client: TestClient, fake: LineageOpenAlex, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/research/api-status", json={"enabled": False})
    paper_id = _upload(client)
    monkeypatch.setattr(paper_parents, "choose_parents", _choose({"Lost": "Sharp", "Sharp": "Speech"}))
    sharp_id = _upload(client, _sharp_tei('<idno type="arXiv">1805.04623</idno>'))

    paper = client.get(f"/research/studies/{paper_id}").json()
    [parent] = [p for p in paper["parents"] if p["is_parent"]]
    assert (parent["study_id"], parent["state"]) == (sharp_id, "paper")  # the Lead became this Paper
    assert client.get("/research/studies", params={"state": "lead", "q": "Sharp"}).json() == []
    # Ancestors come through the uploaded Parent, even with the API off.
    assert _titles(paper["ancestors"]) == ["Speech and Language Processing"]
    assert fake.requests == []


def test_api_off_upload_without_ids_asks_before_merging(
    client: TestClient, fake: LineageOpenAlex, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/research/api-status", json={"enabled": False})
    paper_id = _upload(client)
    monkeypatch.setattr(paper_parents, "choose_parents", _choose({"Lost": "Sharp", "Sharp": "Speech"}))
    sharp_id = _upload(client, _sharp_tei(""))

    sharp = client.get(f"/research/studies/{sharp_id}").json()
    assert sharp["possible_match"]["title"] == "Sharp Nearby, Fuzzy Far Away"
    client.post(f"/research/studies/{sharp_id}/identity", json={"same": True})
    _settle()

    paper = client.get(f"/research/studies/{paper_id}").json()
    [parent] = [p for p in paper["parents"] if p["is_parent"]]
    assert (parent["study_id"], parent["state"]) == (sharp_id, "paper")
    assert _titles(paper["ancestors"]) == ["Speech and Language Processing"]
