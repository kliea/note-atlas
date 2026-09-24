"""Research Track slice 4: choosing Parent Papers, the user's marks, and S2 signals."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import grobid, paper_extract, paper_parents, research_jobs, s2
from app.db import init_db
from app.main import app
from app.paper_parents import Candidate, ParentJudgement
from tests.test_research import FIELDS, LIMITATION, TEI


def _cand(sid: int, mentions: int = 0, sections: tuple[str, ...] = (), influential: bool = False) -> Candidate:
    return Candidate(
        study_id=sid,
        title=f"Reference {sid}",
        year=2020,
        mention_count=mentions,
        contexts=[{"section": s, "sentence": f"We use [{sid}]."} for s in sections],
        influential=influential,
    )


# --- heuristics ------------------------------------------------------------------------


def test_section_weights() -> None:
    assert paper_parents.section_weight("3. Proposed Method") == 3.0
    assert paper_parents.section_weight("IV. RESULTS AND DISCUSSION") == 2.0
    assert paper_parents.section_weight("II. Related Work") == 1.0
    assert paper_parents.section_weight("Conclusion") == 1.5


def test_citations_linked_detects_unlinked_papers() -> None:
    assert not paper_parents.citations_linked([_cand(i) for i in range(15)])  # e.g. the review paper
    assert paper_parents.citations_linked([_cand(i, mentions=1) for i in range(22)])
    assert not paper_parents.citations_linked([])


def test_shortlist_prefers_method_citations_and_s2_influence() -> None:
    intro = _cand(1, mentions=2, sections=("Introduction", "Related work"))
    method = _cand(2, mentions=1, sections=("Method",))
    influential = _cand(3, mentions=1, sections=("Introduction",), influential=True)
    uncited = _cand(4)
    ranked = paper_parents.shortlist([intro, method, influential, uncited])
    assert [c.study_id for c in ranked] == [3, 2, 1]
    assert len(paper_parents.shortlist([_cand(i, mentions=1, sections=("Method",)) for i in range(40)])) == 15


def test_method_text_uses_method_sections_or_body_start() -> None:
    sections = [("Introduction", "why"), ("3 Methodology", "how we did it"), ("Results", "what")]
    assert paper_parents.method_text(sections, "body") == "## 3 Methodology\nhow we did it"
    assert paper_parents.method_text([("Intro", "x")], "B" * 20_000) == "B" * 12_000


# --- model prompts -------------------------------------------------------------------


class _FakeChat:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.kwargs: dict[str, Any] = {}

    def __call__(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.prompts.append(messages[0]["content"])
        self.kwargs = kwargs
        return json.dumps(self.reply)


def test_judgements_are_matched_by_title_not_number(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChat(
        {
            "judgements": [
                # Numbers swapped by the model; titles are right.
                {"number": 1, "title": "Reference 10", "builds_on": 9, "reason": "builds on 10"},
                {"number": 0, "title": "Reference 11", "builds_on": 7, "reason": "uses 11"},
                {"number": 0, "title": "Something not in the list at all", "builds_on": 9, "reason": "?"},
            ]
        }
    )
    monkeypatch.setattr(paper_parents, "chat", fake)
    judged = paper_parents.judge_linked("T", "A", "", [_cand(10, 1, ("Method",)), _cand(11, 1, ("Method",))])
    assert judged == {
        10: ParentJudgement(score=0.9, reason="builds on 10"),
        11: ParentJudgement(score=0.7, reason="uses 11"),
    }


def test_judge_linked_sends_contexts_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChat(
        {
            "judgements": [
                {"number": 0, "builds_on": 9, "reason": "extends its method"},
                {"number": 1, "builds_on": 14, "reason": "  uses   its dataset "},
                {"number": 7, "builds_on": 9, "reason": "no such reference"},
            ]
        }
    )
    monkeypatch.setattr(paper_parents, "chat", fake)
    judged = paper_parents.judge_linked("T", "A", "We extend [10].", [_cand(10, 1, ("Method",)), _cand(11, 1, ("Data",))])
    assert judged == {
        10: ParentJudgement(score=0.9, reason="extends its method"),
        11: ParentJudgement(score=1.0, reason="uses its dataset"),
    }
    assert "[Method] We use [10]." in fake.prompts[0]
    assert "METHOD:\nWe extend [10]." in fake.prompts[0]
    assert "Pick the references this paper BUILDS ON" in fake.prompts[0]
    assert fake.kwargs["priority"] == "research"


@pytest.mark.real_parents
def test_unlinked_paper_is_judged_against_its_method(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChat({"judgements": [{"number": 1, "builds_on": 8, "reason": "uses its dataset"}]})
    monkeypatch.setattr(paper_parents, "chat", fake)
    judged = paper_parents.choose_parents(
        "T", "A", [_cand(20), _cand(21)], [("Methodology", "We apply Apriori to DOH data.")], "body"
    )
    assert judged == {21: ParentJudgement(score=0.8, reason="uses its dataset")}
    assert "METHOD:\n## Methodology\nWe apply Apriori" in fake.prompts[0]
    assert "1. Reference 21 (2020)" in fake.prompts[0]


# --- pipeline, marks, refresh ---------------------------------------------------------


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setenv("S2_API_KEY", "")
    init_db()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    return TestClient(app)


def _judge_by_title(scores: dict[str, tuple[float, str]]):
    def choose(_title: str, _abstract: str, candidates: list[Candidate], _sections: Any, _body: str):
        return {c.study_id: ParentJudgement(*scores[c.title]) for c in candidates if c.title in scores}

    return choose


SHARP = "Sharp Nearby, Fuzzy Far Away"
BOOK = "Speech and Language Processing"


def _paper(client: TestClient) -> int:
    paper_id = client.post("/research/papers", files=[("files", ("p.pdf", _pdf(), "application/pdf"))]).json()[0]["id"]
    while research_jobs.process_next_job():
        pass
    return paper_id


def test_parents_scored_with_reasons_and_threshold(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        paper_parents, "choose_parents", _judge_by_title({SHARP: (0.9, "extends its method"), BOOK: (0.3, "background only")})
    )
    paper = client.get(f"/research/studies/{_paper(client)}").json()
    assert paper["job"]["status"] == "done"
    parents = paper["parents"]
    assert [(p["title"], p["is_parent"], p["reason"]) for p in parents] == [
        (SHARP, True, "extends its method"),
        (BOOK, False, "background only"),
    ]
    assert parents[0]["mention_count"] == 2


def test_marks_override_the_model_and_survive_refresh(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        paper_parents, "choose_parents", _judge_by_title({SHARP: (0.9, "extends its method"), BOOK: (0.3, "background only")})
    )
    paper_id = _paper(client)
    sharp_id, book_id = (p["study_id"] for p in client.get(f"/research/studies/{paper_id}").json()["parents"])

    client.put(f"/research/studies/{paper_id}/parents/{book_id}", json={"mark": "pinned"})
    marked = client.put(f"/research/studies/{paper_id}/parents/{sharp_id}", json={"mark": "unpinned"}).json()
    assert [(p["study_id"], p["is_parent"], p["mark"]) for p in marked["parents"]] == [
        (book_id, True, "pinned"),
        (sharp_id, False, "unpinned"),
    ]

    # The model now disagrees completely; the user's marks still win.
    monkeypatch.setattr(
        paper_parents, "choose_parents", _judge_by_title({SHARP: (1.0, "core method"), BOOK: (0.0, "never used")})
    )
    refreshed = client.post(f"/research/studies/{paper_id}/parents/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["job"] == {"status": "queued", "step": "parents", "error": None, "queue_position": 1}
    assert client.post(f"/research/studies/{paper_id}/parents/refresh").status_code == 409
    while research_jobs.process_next_job():
        pass
    parents = client.get(f"/research/studies/{paper_id}").json()["parents"]
    by_id = {p["study_id"]: p for p in parents}
    assert by_id[book_id]["is_parent"] and by_id[book_id]["reason"] == "never used"
    assert not by_id[sharp_id]["is_parent"] and by_id[sharp_id]["reason"] == "core method"

    cleared = client.put(f"/research/studies/{paper_id}/parents/{sharp_id}", json={"mark": None}).json()
    assert {p["study_id"]: p["is_parent"] for p in cleared["parents"]}[sharp_id] is True


def test_marking_something_that_isnt_a_reference_is_rejected(client: TestClient) -> None:
    paper_id = _paper(client)
    assert client.put(f"/research/studies/{paper_id}/parents/{paper_id}", json={"mark": "pinned"}).status_code == 404


def test_s2_influence_reaches_the_candidates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Candidate] = []

    def choose(_t: str, _a: str, candidates: list[Candidate], _s: Any, _b: str) -> dict:
        seen.extend(candidates)
        return {}

    monkeypatch.setattr(paper_parents, "choose_parents", choose)
    monkeypatch.setattr(
        s2, "reference_signals", lambda _doi: {"title:sharp nearby fuzzy far away": (True, ["methodology"])}
    )
    _paper(client)
    by_title = {c.title: c for c in seen}
    assert by_title[SHARP].influential and by_title[SHARP].intents == ["methodology"]
    assert not by_title[BOOK].influential


# --- Semantic Scholar client ----------------------------------------------------------


class _Resp:
    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self.text = json.dumps(body)


def test_s2_needs_the_users_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def get(url: str, **kwargs: Any) -> _Resp:
        calls.append({"url": url, **kwargs})
        return _Resp(
            {
                "data": [
                    {
                        "isInfluential": True,
                        "intents": ["methodology"],
                        "citedPaper": {"title": "Sharp Nearby", "externalIds": {"DOI": "10.18653/V1/P18-1027"}},
                    }
                ]
            }
        )

    monkeypatch.setattr(s2.httpx, "get", get)
    assert s2.reference_signals("10.1/x") == {}
    assert calls == []

    monkeypatch.setenv("S2_API_KEY", "user-key")
    signals = s2.reference_signals("https://doi.org/10.1/X")
    assert signals["doi:10.18653/v1/p18-1027"] == (True, ["methodology"])
    assert signals["title:sharp nearby"] == (True, ["methodology"])
    assert calls[0]["headers"]["x-api-key"] == "user-key"
    assert calls[0]["url"].endswith("/paper/DOI:10.1/x/references")
    s2.reference_signals("10.1/x")
    assert len(calls) == 1  # cached


def test_s2_stays_quiet_with_the_api_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(s2.httpx, "get", lambda url, **_kw: calls.append(url))
    monkeypatch.setenv("S2_API_KEY", "user-key")
    assert client.put("/research/api-status", json={"enabled": False}).status_code == 200
    assert s2.reference_signals("10.1/x") == {}
    assert calls == []


def test_merging_two_references_keeps_score_and_mark(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import research_store

    monkeypatch.setattr(
        paper_parents, "choose_parents", _judge_by_title({SHARP: (0.4, "weak"), BOOK: (0.9, "core method")})
    )
    paper_id = _paper(client)
    by_title = {p["title"]: p["study_id"] for p in client.get(f"/research/studies/{paper_id}").json()["parents"]}
    client.put(f"/research/studies/{paper_id}/parents/{by_title[SHARP]}", json={"mark": "pinned"})

    # Both references turn out to be one work: BOOK folds into SHARP.
    research_store.merge_studies(by_title[SHARP], by_title[BOOK])
    [merged] = client.get(f"/research/studies/{paper_id}").json()["parents"]
    assert merged["study_id"] == by_title[SHARP]
    assert (merged["score"], merged["reason"], merged["mark"]) == (0.9, "core method", "pinned")
