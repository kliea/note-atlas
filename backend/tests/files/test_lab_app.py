"""Files F5: the Streamlit lab app, run headless end to end (temp DB and Chroma, Ollama mocked)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.files import answer, repo, service

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

LAB_APP = Path(__file__).resolve().parents[3] / "lab" / "app.py"
TXT = ("Chunking splits documents into pieces before embedding. " * 25).encode()  # 3 chunks


@pytest.fixture(autouse=True)
def chat(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    models: list[str] = []

    def fake(_messages: list[dict[str, str]], *, model: str | None = None, **_: Any) -> Iterator[str]:
        models.append(str(model))
        yield from ["Chunks are ", "pieces."]

    monkeypatch.setattr("app.llm.chat_stream", fake)
    return models


def _run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _texts(elements: Any) -> list[str]:
    return [str(e.value) for e in elements]


def test_lab_app_starts_on_an_empty_knowledge_base() -> None:
    at = _run(AppTest.from_file(str(LAB_APP), default_timeout=60))
    assert at.title[0].value == "📚 Simple RAG Application using Phi-3"
    assert "Stored Chunks: 0" in _texts(at.sidebar.markdown)
    assert "Document Upload" in _texts(at.sidebar.header)
    assert "Ask Questions" in _texts(at.header)


def test_build_ask_history_and_clear(chat: list[str]) -> None:
    folder = service.create_folder("Lectures")
    service.add_files(folder.id, [("notes.txt", TXT)])  # AppTest can't drive file_uploader
    at = _run(AppTest.from_file(str(LAB_APP), default_timeout=60))

    build = next(b for b in at.sidebar.button if b.label == "Build Knowledge Base")
    build.click()
    _run(at)
    assert "Stored Chunks: 3" in _texts(at.sidebar.markdown)
    assert "3 chunks indexed." in _texts(at.sidebar.success)
    assert repo.list_documents(folder.id)[0].status == "indexed"

    at.text_input[0].input("What is chunking?")
    next(b for b in at.button if b.label == "Ask").click()
    _run(at)
    assert chat == ["phi3"]
    assert "Answer" in _texts(at.subheader) and "Retrieved Context" in _texts(at.subheader)
    assert "Retrieved 3 chunks." in _texts(at.caption)
    assert [e.label for e in at.main.expander] == [
        "Chunk 1 · notes.txt · p.1",
        "Chunk 2 · notes.txt · p.1",
        "Chunk 3 · notes.txt · p.1",
    ]
    assert "Chat History" in _texts(at.subheader)
    saved = service.chat_history()
    assert [(a.question, a.answer, a.model) for a in saved] == [("What is chunking?", "Chunks are pieces.", "phi3")]

    clear = next(b for b in at.sidebar.button if b.label == "Clear Knowledge Base")
    clear.click()
    _run(at)
    assert "Stored Chunks: 0" in _texts(at.sidebar.markdown)
    assert repo.list_documents(folder.id)[0].status == "uploaded"


def test_off_topic_answer_is_shown_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.llm.chat_stream", lambda _m, **_: iter([answer.REFUSAL]))
    folder = service.create_folder("Lectures")
    service.add_files(folder.id, [("notes.txt", TXT)])
    service.build_folder(folder.id)
    at = _run(AppTest.from_file(str(LAB_APP), default_timeout=60))
    at.text_input[0].input("What is the capital of France?")
    next(b for b in at.button if b.label == "Ask").click()
    _run(at)
    assert service.chat_history()[0].answer == answer.REFUSAL


def test_asking_before_building_explains_without_the_model(chat: list[str]) -> None:
    service.create_folder("Lectures")
    at = _run(AppTest.from_file(str(LAB_APP), default_timeout=60))
    at.text_input[0].input("Anything?")
    next(b for b in at.button if b.label == "Ask").click()
    _run(at)
    assert service.EMPTY_SCOPE in _texts(at.info)
    assert chat == []
