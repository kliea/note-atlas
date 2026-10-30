"""Files F4: retrieval, the lab prompt with phi3, streamed Ask, and Chat History (Ollama mocked)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.config import ollama_model
from app.files import answer, repo, service

from .conftest import FakeEmbedder

TXT_A = ("Retrieval augmented generation grounds answers in documents. " * 40).encode()  # 5 chunks
TXT_B = ("Vector databases store embeddings for similarity search. " * 10).encode()  # 2 chunks


class FakeChat:
    def __init__(self, reply: list[str]) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, str]], *, model: str | None = None, **_: Any) -> Iterator[str]:
        self.calls.append({"messages": messages, "model": model})
        yield from self.reply

    @property
    def prompt(self) -> str:
        return self.calls[-1]["messages"][0]["content"]


@pytest.fixture(autouse=True)
def chat(monkeypatch: pytest.MonkeyPatch) -> FakeChat:
    fake = FakeChat(["Grounded ", "answer."])
    monkeypatch.setattr("app.llm.chat_stream", fake)
    return fake


def _built(name: str, *files: tuple[str, bytes]) -> int:
    folder = repo.create_folder(name)
    repo.add_documents(folder.id, list(files))
    service.build_folder(folder.id)
    return folder.id


def _events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_prompt_is_the_lab_prompt_with_exactly_the_retrieved_chunks(chat: FakeChat) -> None:
    _built("Lectures", ("a.txt", TXT_A))
    plan, text = service.ask("What grounds answers?")

    assert text == "Grounded answer."
    assert len(plan.chunks) == 3  # lab top-k
    assert chat.calls[-1]["model"] == "phi3"
    messages = chat.calls[-1]["messages"]
    assert [m["role"] for m in messages] == ["user"]
    context = "\n\n".join(c.text for c in plan.chunks)
    assert chat.prompt == answer.build_prompt("What grounds answers?", plan.chunks)
    assert f"Context:\n{context}\n\nQuestion:\nWhat grounds answers?\n" in chat.prompt
    assert chat.prompt.startswith("You are a helpful assistant.\n\nUse ONLY the context below.")
    assert '"The information is not available in the uploaded documents."' in chat.prompt
    assert chat.prompt.rstrip().endswith("Answer:")


def test_retrieved_chunks_carry_source_and_score() -> None:
    folder_id = _built("Lectures", ("week1.txt", TXT_A))
    plan, _ = service.ask("grounding")
    chunk = plan.chunks[0]
    assert chunk.filename == "week1.txt" and chunk.page_start == 1 and chunk.folder_id == folder_id
    assert chunk.id == f"{chunk.document_id}:{chunk.chunk_idx}"
    assert -1.0 <= chunk.score <= 1.0
    assert [c.score for c in plan.chunks] == sorted((c.score for c in plan.chunks), reverse=True)


def test_top_k_is_configurable_per_request() -> None:
    _built("Lectures", ("a.txt", TXT_A))
    assert len(service.ask("q", top_k=5)[0].chunks) == 5
    assert len(service.ask("q", top_k=1)[0].chunks) == 1


def test_folder_scope_excludes_other_folders() -> None:
    lectures = _built("Lectures", ("a.txt", TXT_A))
    labs = _built("Labs", ("b.txt", TXT_B))

    only_labs, _ = service.ask("vectors", folder_ids=[labs])
    assert {c.folder_id for c in only_labs.chunks} == {labs}
    assert len(only_labs.chunks) == 2  # fewer than k exist in scope

    only_lectures, _ = service.ask("vectors", folder_ids=[lectures])
    assert {c.folder_id for c in only_lectures.chunks} == {lectures}

    both, _ = service.ask("vectors", folder_ids=[labs, lectures], top_k=7)
    assert {c.folder_id for c in both.chunks} == {labs, lectures}
    everything, _ = service.ask("vectors", top_k=7)
    assert len(everything.chunks) == 7


def test_empty_index_never_calls_the_embedder_or_model(chat: FakeChat, embedder: FakeEmbedder) -> None:
    plan, text = service.ask("anything")
    assert plan.empty_message == service.EMPTY_SCOPE and text == service.EMPTY_SCOPE
    assert chat.calls == [] and embedder.calls == []
    assert repo.list_asks() == []


def test_empty_scope_never_calls_the_model_even_when_other_folders_are_built(
    chat: FakeChat, embedder: FakeEmbedder
) -> None:
    _built("Lectures", ("a.txt", TXT_A))
    unbuilt = repo.create_folder("Unbuilt")
    repo.add_documents(unbuilt.id, [("b.txt", TXT_B)])
    embedder.calls.clear()

    plan, _ = service.ask("anything", folder_ids=[unbuilt.id])
    assert plan.empty_message is not None
    assert chat.calls == [] and embedder.calls == []


def test_score_threshold_refuses_without_the_model(chat: FakeChat, monkeypatch: pytest.MonkeyPatch) -> None:
    _built("Lectures", ("a.txt", TXT_A))
    monkeypatch.setenv("FILES_SCORE_THRESHOLD", "1.01")  # nothing can clear it
    plan, text = service.ask("anything")
    assert plan.chunks == [] and text == answer.REFUSAL
    assert chat.calls == []
    saved = repo.list_asks()[0]
    assert saved.answer == answer.REFUSAL and saved.model.startswith("none")


def test_no_threshold_by_default_so_every_top_k_chunk_reaches_the_model(chat: FakeChat) -> None:
    _built("Lectures", ("a.txt", TXT_A))
    plan, _ = service.ask("completely unrelated question about cooking")
    assert len(plan.chunks) == 3 and len(chat.calls) == 1


def test_history_is_written_newest_first() -> None:
    lectures = _built("Lectures", ("a.txt", TXT_A))
    service.ask("first?", folder_ids=[lectures])
    service.ask("second?")
    first, second = reversed(repo.list_asks())
    assert (first.question, first.folder_ids, first.model) == ("first?", [lectures], "phi3")
    assert first.answer == "Grounded answer." and len(first.chunks) == 3
    assert first.chunks[0].filename == "a.txt"
    assert second.folder_ids is None
    assert [a.question for a in repo.list_asks()] == ["second?", "first?"]


# --- HTTP -------------------------------------------------------------------------


def test_ask_streams_tokens_then_chunks_and_history(client: TestClient) -> None:
    folder_id = _built("Lectures", ("week1.txt", TXT_A))
    response = client.post("/files/ask", json={"question": "What grounds answers?", "folder_ids": [folder_id]})
    assert response.status_code == 200
    events = _events(response)
    assert [e for e, _ in events] == ["token", "token", "done"]
    assert "".join(d["text"] for e, d in events if e == "token") == "Grounded answer."
    done = events[-1][1]
    assert done["empty"] is None
    assert len(done["chunks"]) == 3
    assert {(c["filename"], c["page_start"]) for c in done["chunks"]} == {("week1.txt", 1)}
    assert done["ask"]["answer"] == "Grounded answer." and done["ask"]["model"] == "phi3"

    history = client.get("/files/asks").json()
    assert [h["question"] for h in history] == ["What grounds answers?"]
    assert client.delete("/files/asks").status_code == 204
    assert client.get("/files/asks").json() == []


def test_ask_on_an_empty_index_explains_without_the_model(client: TestClient, chat: FakeChat) -> None:
    events = _events(client.post("/files/ask", json={"question": "hello"}))
    assert events == [("done", {"empty": service.EMPTY_SCOPE, "chunks": [], "ask": None})]
    assert chat.calls == []


def test_model_failure_is_an_error_event_and_not_saved(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _built("Lectures", ("a.txt", TXT_A))

    def broken(_messages: list[dict[str, str]], **_: Any) -> Iterator[str]:
        raise llm.LlmError("Ollama model phi3 not found (HTTP 404)")
        yield ""  # pragma: no cover

    monkeypatch.setattr("app.llm.chat_stream", broken)
    events = _events(client.post("/files/ask", json={"question": "q"}))
    assert events == [("error", {"detail": "Ollama model phi3 not found (HTTP 404)"})]
    assert repo.list_asks() == []


def test_blank_question_is_rejected(client: TestClient) -> None:
    assert client.post("/files/ask", json={"question": "   "}).status_code == 400
    assert client.post("/files/ask", json={"question": ""}).status_code == 422


# --- shared client --------------------------------------------------------------------


def test_per_call_model_overrides_only_that_call() -> None:
    messages = [{"role": "user", "content": "hi"}]
    assert llm._base_payload(messages, stream=True, temperature=None)["model"] == ollama_model()
    assert llm._base_payload(messages, stream=True, temperature=None, model="phi3")["model"] == "phi3"
