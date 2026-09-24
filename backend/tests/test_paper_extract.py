"""Research Track slice 2: Extraction, quote-verified Limitations, Claims, and model priority."""

from __future__ import annotations

import json
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import grobid, llm, paper_extract, research_jobs, research_store
from app.db import init_db
from app.llm import LlmError
from app.main import app
from tests.test_research import FIELDS, LIMITATION, TEI

# --- quote verification --------------------------------------------------------------

PAPER_TEXT = (
    "Applying a COCO-pretrained YOLOv8n to VisDrone imagery introduces two distinct, unre- "
    "solved domain gaps that likely affect detection metrics more strongly than the choice of "
    "feature configuration. Figure 3: Mean inlier reprojection residuals were not logged at "
    "either scale and remain a direction for follow-up."
)


def test_quote_found_despite_hyphenation_and_punctuation() -> None:
    quote = (
        "Applying a COCO-pretrained YOLOv8n to VisDrone imagery introduces two distinct, "
        "unresolved domain gaps that likely affect detection metrics"
    )
    assert paper_extract.quote_in_text(quote, PAPER_TEXT)


def test_quote_found_in_a_caption() -> None:
    assert paper_extract.quote_in_text(
        "Mean inlier reprojection residuals were not logged at either scale", PAPER_TEXT
    )


def test_invented_or_trivial_quotes_are_rejected() -> None:
    assert not paper_extract.quote_in_text(
        "The dataset lacks demographic diversity among document owners", PAPER_TEXT
    )
    assert not paper_extract.quote_in_text("domain gaps", PAPER_TEXT)


# --- chunking ------------------------------------------------------------------------


def test_short_body_is_one_chunk() -> None:
    assert paper_extract.chunk_body("## Intro\nshort") == ["## Intro\nshort"]


def test_long_body_splits_on_sections_under_the_limit() -> None:
    body = "\n".join(f"## Section {i}\n" + ("word " * 60) for i in range(10))
    chunks = paper_extract.chunk_body(body, max_chars=700)
    assert len(chunks) > 1
    assert all(len(chunk) <= 700 for chunk in chunks)
    assert all(chunk.startswith("## Section") for chunk in chunks)
    assert "".join(chunks) == body


# --- prompts go to the model with a schema, at research priority ---------------------


class _FakeChat:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append({"prompt": messages[0]["content"], **kwargs})
        return json.dumps(self.replies.pop(0))


FIELDS_REPLY = {
    "research_question": "Q?",
    "contributions": ["A new dataset.", "  "],
    "method": "M",
    "key_results": "R",
    "scope": "S",
}


def test_extract_fields_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChat([FIELDS_REPLY])
    monkeypatch.setattr(paper_extract, "chat", fake)
    fields = paper_extract.extract_fields("T", "A", "## Intro\nbody")
    assert fields.contributions == ["A new dataset."]
    (call,) = fake.calls
    assert call["priority"] == "research"
    assert call["temperature"] == 0
    assert call["schema"]["required"] == ["research_question", "contributions", "method", "key_results", "scope"]
    assert "A finding or a number is NOT a contribution" in call["prompt"]


def test_extract_fields_chunks_then_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChat([FIELDS_REPLY, FIELDS_REPLY, FIELDS_REPLY])
    monkeypatch.setattr(paper_extract, "chat", fake)
    monkeypatch.setattr(paper_extract, "chunk_body", lambda _body: ["## One\n...", "## Two\n..."])
    paper_extract.extract_fields("T", "A", "## One\n...\n## Two\n...")
    assert len(fake.calls) == 3
    assert "part 1 of 2" in fake.calls[0]["prompt"]
    assert "Merge them" in fake.calls[2]["prompt"]


def test_limitations_keep_only_verified_and_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChat(
        [
            {
                "limitations": [
                    {"text": "Residuals weren't logged.", "quote": "Mean inlier reprojection residuals were not logged at either scale"},
                    {"text": "No demographic diversity.", "quote": "The dataset lacks demographic diversity among owners"},
                    {"text": "Uses VisDrone.", "quote": "Applying a COCO-pretrained YOLOv8n to VisDrone imagery"},
                ]
            },
            # Second check, for the two quotes that were found in the text.
            {"verdicts": [{"number": 0, "admits_weakness": True}, {"number": 1, "admits_weakness": False}]},
        ]
    )
    monkeypatch.setattr(paper_extract, "chat", fake)
    kept = paper_extract.extract_limitations("## Body\n" + PAPER_TEXT, PAPER_TEXT)
    assert [c.text for c in kept] == ["Residuals weren't logged."]
    assert "Mean inlier reprojection residuals" in fake.calls[1]["prompt"]
    assert "demographic" not in fake.calls[1]["prompt"]


# --- llm client ----------------------------------------------------------------------


def test_context_size_buckets() -> None:
    assert llm.context_size([{"role": "user", "content": "hi"}]) == 4096
    assert llm.context_size([{"role": "user", "content": "x" * 30_000}]) == 16384
    with pytest.raises(LlmError):
        llm.context_size([{"role": "user", "content": "x" * 200_000}])


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_chat_never_lets_ollama_truncate(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def urlopen(request: Any, timeout: float) -> _Response:
        sent.append(json.loads(request.data))
        return _Response({"message": {"content": "{}"}})

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    llm.chat([{"role": "user", "content": "x" * 20_000}], schema={"type": "object"}, temperature=0)
    (payload,) = sent
    assert payload["truncate"] is False
    assert payload["shift"] is False
    assert payload["options"] == {"num_ctx": 8192, "temperature": 0}
    assert payload["format"] == {"type": "object"}


def test_research_call_waits_for_board_call(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    board_started = threading.Event()
    release_board = threading.Event()

    def urlopen(request: Any, timeout: float) -> _Response:
        content = json.loads(request.data)["messages"][0]["content"]
        if content == "board":
            board_started.set()
            release_board.wait(2)
        order.append(content)
        return _Response({"message": {"content": "ok"}})

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    board = threading.Thread(target=lambda: llm.chat([{"role": "user", "content": "board"}]))
    board.start()
    board_started.wait(2)
    research = threading.Thread(
        target=lambda: llm.chat([{"role": "user", "content": "research"}], priority="research")
    )
    research.start()
    time.sleep(0.1)
    assert order == []  # research is held while the board call is in flight
    release_board.set()
    board.join(2)
    research.join(2)
    assert order == ["board", "research"]


# --- pipeline and Claims API ---------------------------------------------------------


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    init_db()
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS)
    monkeypatch.setattr(paper_extract, "extract_limitations", lambda *_: [LIMITATION])
    return TestClient(app)


def _uploaded_paper(client: TestClient) -> int:
    response = client.post("/research/papers", files=[("files", ("p.pdf", _pdf_bytes(), "application/pdf"))])
    study_id = response.json()[0]["id"]
    while research_jobs.process_next_job():
        pass
    return study_id


def test_pipeline_fills_extraction_and_claims(client: TestClient) -> None:
    study = client.get(f"/research/studies/{_uploaded_paper(client)}").json()
    assert study["job"]["status"] == "done"
    assert study["research_question"] == "How do models use long contexts?"
    assert study["scope"].startswith("2023 decoder LMs")
    assert study["extraction_model"] == "qwen3:4b"
    assert study["extracted_at"]
    kinds = [(c["kind"], c["author"]) for c in study["claims"]]
    assert kinds == [("contribution", "paper"), ("contribution", "paper"), ("limitation", "paper")]
    assert study["claims"][2]["quote"] == "we leave newer models to future work"


def test_model_failure_retries_from_the_failed_step(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def overflow(_title: str, _abstract: str, _body: str) -> paper_extract.ExtractedFields:
        raise LlmError("HTTP 400")

    parses: list[int] = []
    real_parse = research_store.apply_parse
    monkeypatch.setattr(research_store, "apply_parse", lambda sid, parsed: (parses.append(sid), real_parse(sid, parsed)))
    monkeypatch.setattr(paper_extract, "extract_fields", overflow)
    study_id = _uploaded_paper(client)
    job = client.get(f"/research/studies/{study_id}").json()["job"]
    assert (job["status"], job["step"]) == ("failed", "extract")
    assert "HTTP 400" in job["error"]

    monkeypatch.setattr(paper_extract, "extract_fields", lambda *_: FIELDS_FOR_RETRY)
    client.post(f"/research/studies/{study_id}/retry")
    while research_jobs.process_next_job():
        pass
    assert client.get(f"/research/studies/{study_id}").json()["job"]["status"] == "done"
    assert parses == [study_id]  # parse ran once; the retry resumed at extract


FIELDS_FOR_RETRY = paper_extract.ExtractedFields("Q", ["C"], "M", "R", "S")


def test_edit_add_and_delete_claims(client: TestClient) -> None:
    study_id = _uploaded_paper(client)
    claims = client.get(f"/research/studies/{study_id}").json()["claims"]
    contribution, limitation = claims[0], claims[2]

    edited = client.patch(f"/research/claims/{contribution['id']}", json={"text": "Reworded."}).json()
    assert (edited["text"], edited["edited"], edited["author"]) == ("Reworded.", True, "paper")
    assert edited["original_text"] == contribution["text"]
    again = client.patch(f"/research/claims/{contribution['id']}", json={"text": "Reworded twice."}).json()
    assert again["original_text"] == contribution["text"]  # the first original is kept

    mine = client.post(f"/research/studies/{study_id}/claims", json={"text": "No reranking baseline."})
    assert mine.status_code == 201
    assert (mine.json()["author"], mine.json()["kind"]) == ("reader", "limitation")

    assert client.delete(f"/research/claims/{limitation['id']}").status_code == 204
    texts = [c["text"] for c in client.get(f"/research/studies/{study_id}").json()["claims"]]
    assert limitation["text"] not in texts
    assert "No reranking baseline." in texts
    assert client.delete(f"/research/claims/{limitation['id']}").status_code == 404


def test_rerunning_extraction_keeps_edits_and_never_restores_deleted(client: TestClient) -> None:
    study_id = _uploaded_paper(client)
    claims = client.get(f"/research/studies/{study_id}").json()["claims"]
    client.patch(f"/research/claims/{claims[0]['id']}", json={"text": "My wording."})
    client.delete(f"/research/claims/{claims[2]['id']}")
    client.post(f"/research/studies/{study_id}/claims", json={"text": "Mine."})

    research_store.replace_paper_claims(
        study_id, "contribution", [(c, None) for c in (claims[0]["text"], claims[1]["text"])]
    )
    research_store.replace_paper_claims(study_id, "limitation", [(claims[2]["text"], "q")])

    texts = [c["text"] for c in client.get(f"/research/studies/{study_id}").json()["claims"]]
    assert texts.count("My wording.") == 1
    assert claims[0]["text"] not in texts  # the edited Claim isn't duplicated by its original
    assert claims[1]["text"] in texts
    assert claims[2]["text"] not in texts  # deleted stays deleted
    assert "Mine." in texts


def test_reader_claim_needs_a_paper(client: TestClient) -> None:
    study_id = _uploaded_paper(client)
    lead_id = client.get(f"/research/studies/{study_id}").json()["references"][0]["study_id"]
    assert client.post(f"/research/studies/{lead_id}/claims", json={"text": "x"}).status_code == 404
