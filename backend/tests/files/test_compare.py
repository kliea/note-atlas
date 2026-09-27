"""Files F7: the comparison harness (Ollama and MiniLM faked, temp dirs)."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.files import answer, compare, repo, service, store

from .conftest import fake_vector

DOC = ("Retrieval grounds answers in documents. ChromaDB stores vectors. " * 30).encode()  # 5 chunks
LAB_QUESTIONS = Path(__file__).resolve().parents[3] / "lab" / "eval_questions.yaml"


class FakeChat:
    def __init__(self) -> None:
        self.models: list[str | None] = []

    def __call__(self, messages: list[dict[str, str]], *, model: str | None = None, **_: Any) -> Iterator[str]:
        self.models.append(model)
        prompt = messages[0]["content"]
        yield answer.REFUSAL if "France" in prompt else "An answer from the context."


class FakeMiniLM:
    def encode(self, texts: list[str], **_: Any) -> list[list[float]]:
        return [fake_vector("minilm:" + t)[:4] for t in texts]  # a different size, as MiniLM's 384 would be


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> FakeChat:
    fake = FakeChat()
    monkeypatch.setattr("app.llm.chat_stream", fake)
    monkeypatch.setattr("app.files.embed._sentence_transformer", lambda _name: FakeMiniLM())
    return fake


@pytest.fixture
def lab_folder() -> int:
    folder = service.create_folder("Lab")
    service.add_files(folder.id, [("handout.txt", DOC)])
    service.build_folder(folder.id)
    return folder.id


QUESTIONS = [
    compare.Question("What stores vectors?", compare.IN_SCOPE, "handout", (1,)),
    compare.Question("What stores vectors, page 9?", compare.IN_SCOPE, "handout", (9,)),
    compare.Question("What is the capital of France?", compare.OFF_TOPIC),
]


def _plan(*variants: compare.Variant) -> compare.Plan:
    return compare.Plan(folder="Lab", questions=list(QUESTIONS), variants=list(variants or compare.DEFAULT_VARIANTS))


def test_every_variant_answers_every_question_and_writes_reports(
    chat: FakeChat, lab_folder: int, tmp_path: Path
) -> None:
    rows, csv_path, md_path = compare.run(_plan(), tmp_path / "eval", log=lambda _m: None)

    assert len(rows) == len(compare.DEFAULT_VARIANTS) * len(QUESTIONS)
    assert not [r.error for r in rows if r.error]
    baseline = {r.question: r for r in rows if r.variant == "baseline"}
    assert baseline["What is the capital of France?"].refused is True
    assert baseline["What stores vectors?"].refused is False
    assert baseline["What stores vectors?"].hit is True
    assert baseline["What stores vectors, page 9?"].hit is False  # right file, wrong page
    assert baseline["What is the capital of France?"].hit is None
    assert all(len(r.sources) == 3 and r.sources[0].startswith("handout.txt · p.") for r in baseline.values())

    with csv_path.open(encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == len(rows) and records[0]["variant"] == "baseline"
    assert set(records[0]) >= {"answer", "refused", "sources", "hit", "total_ms", "model"}

    md = md_path.read_text(encoding="utf-8")
    assert "| baseline | lab defaults | 1/1 (100%) | 2/2 (100%) | 1/2 (50%) |" in md
    assert "| hybrid | hybrid on |" in md and "| qwen3-4b | model qwen3:4b |" in md
    assert "| What is the capital of France? | off-topic | R |" in md
    assert "## Best retrieval score" in md and "| nomic-embed-text-500-0 |" in md
    assert all(r.top_score is not None for r in rows)
    assert records[0]["top_score"] != ""


def test_threshold_variant_refuses_without_the_model(chat: FakeChat, lab_folder: int, tmp_path: Path) -> None:
    rows, _, _ = compare.run(
        _plan(compare.Variant("strict", threshold=1.01)), tmp_path / "eval", log=lambda _m: None
    )
    assert all(r.refused and r.model == "none (below threshold)" and r.sources == [] for r in rows)
    assert chat.models == ["phi3"]  # only the warm-up


def test_models_are_warmed_once_and_used_per_variant(chat: FakeChat, lab_folder: int, tmp_path: Path) -> None:
    plan = _plan(compare.BASELINE, compare.Variant("hybrid", hybrid=True), compare.Variant("q", model="qwen3:4b"))
    compare.run(plan, tmp_path / "eval", log=lambda _m: None)
    assert chat.models.count("phi3") == 1 + 2 * len(QUESTIONS)
    assert chat.models.count("qwen3:4b") == 1 + len(QUESTIONS)


def test_index_setups_get_their_own_chroma_and_are_reused(
    chat: FakeChat, lab_folder: int, tmp_path: Path
) -> None:
    out = tmp_path / "eval"
    plan = _plan(compare.BASELINE, compare.Variant("overlap-100", chunk_overlap=100), compare.Variant("minilm", embedder="minilm"))
    logs: list[str] = []
    compare.run(plan, out, log=logs.append)
    assert sorted(p.name for p in (out / "chroma").iterdir()) == [
        "minilm-500-0",
        "nomic-embed-text-500-0",
        "nomic-embed-text-500-100",
    ]
    assert sum("built" in line for line in logs) == 3

    logs.clear()
    compare.run(plan, out, log=logs.append)
    assert sum("reused" in line for line in logs) == 3

    logs.clear()
    compare.run(plan, out, rebuild=True, log=logs.append)
    assert sum("built" in line for line in logs) == 3


def test_the_real_database_index_and_history_are_untouched(
    chat: FakeChat, lab_folder: int, tmp_path: Path
) -> None:
    before_docs = repo.list_documents(lab_folder)
    before_vectors = store.count()
    env_before = {k: os.environ.get(k) for k in ("DB_PATH", "FILES_CHUNK_OVERLAP", "FILES_CHROMA_PATH", "FILES_LLM_MODEL")}

    compare.run(_plan(compare.BASELINE, compare.Variant("overlap-100", chunk_overlap=100)), tmp_path / "eval", log=lambda _m: None)

    assert {k: os.environ.get(k) for k in env_before} == env_before
    assert repo.list_documents(lab_folder) == before_docs
    assert store.count() == before_vectors
    assert service.chat_history() == []


def test_unknown_folder_names_the_ones_that_exist(chat: FakeChat, lab_folder: int, tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="folders: Lab"):
        compare.run(_plan(compare.BASELINE), tmp_path / "eval", folder="Nope", log=lambda _m: None)


def test_the_lab_question_file_parses() -> None:
    plan = compare.load_plan(LAB_QUESTIONS)
    assert plan.folder == "Lab" and plan.top_k == 3
    assert sum(q.kind == compare.IN_SCOPE for q in plan.questions) == 8
    assert sum(q.kind == compare.OFF_TOPIC for q in plan.questions) == 4
    assert plan.variants == list(compare.DEFAULT_VARIANTS)
    persist = next(q for q in plan.questions if "persist" in q.text)
    assert persist.expected_pages == (7,)


def test_custom_variants_and_bad_files_are_checked(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text(
        "folder: Lab\nquestions:\n  - q: Hi?\n    type: off_topic\n"
        "variants:\n  - baseline\n  - name: both\n    hybrid: true\n    chunk_overlap: 50\n"
    )
    plan = compare.load_plan(path)
    assert [v.name for v in plan.variants] == ["baseline", "both"]
    assert plan.variants[1].changes() == "overlap 50, hybrid on"

    path.write_text("questions:\n  - q: Hi?\n    type: sideways\n")
    with pytest.raises(ValueError, match="in_scope or off_topic"):
        compare.load_plan(path)
    path.write_text("questions:\n  - q: Hi?\nvariants:\n  - name: x\n    embedder: word2vec\n")
    with pytest.raises(ValueError, match="unknown embedder"):
        compare.load_plan(path)


def test_cli_runs_selected_variants(chat: FakeChat, lab_folder: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("compare_cli", Path(__file__).resolve().parents[2] / "scripts" / "compare_pipelines.py")
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    questions = tmp_path / "q.yaml"
    questions.write_text("folder: Lab\nquestions:\n  - q: What stores vectors?\n    expected_source: handout\n")
    assert cli.main([str(questions), "--variants", "baseline,hybrid", "--out", str(tmp_path / "eval")]) == 0
    printed = capsys.readouterr().out
    assert "| baseline |" in printed and "| hybrid |" in printed and "Markdown:" in printed
