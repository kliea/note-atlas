from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import apply_point_additions, get_note, init_db, replace_note_extraction
from app.extract import EnrichmentError, enrich
from app.main import app
from app.models import (
    EnrichmentPayload,
    ExtractedTopic,
    NoteDetail,
    Point,
    PointAddition,
    Topic,
)

RAW = (
    "Matsuo Lab lecture\n"
    "Traditional SaaS vs AI-as-a-service > flywheel model\n"
    "vertical AI\n"
    "case study: Matsuo Lab\n"
    "Take notes during the lecture.\n"
)

FLYWHEEL = "Traditional SaaS vs AI-as-a-service > flywheel model"
VERTICAL = "vertical AI"
CASE_STUDY = "case study: Matsuo Lab"
PLAIN = "Take notes during the lecture."

FLYWHEEL_CONTEXT = (
    "A flywheel is a loop where usage improves the product, which attracts more usage. "
    "That compounding loop is the contrast with traditional SaaS, which usually ships a "
    "fixed tool rather than a model that gets better from each customer's data."
)
VERTICAL_CONTEXT = (
    "Vertical AI means models and workflows built for one industry or job, "
    "not a general-purpose assistant."
)
CASE_CONTEXT = (
    "A case study is a worked example of how one organization applied an idea. "
    "Here the name is a pointer to that example, not a claim about this lecture."
)


def _note_with_points() -> NoteDetail:
    return NoteDetail(
        id=1,
        title="Matsuo Lab",
        source="lecture",
        created_at="2026-09-18T00:00:00+00:00",
        raw_text=RAW,
        topics=[
            Topic(
                id=1,
                note_id=1,
                title="Lecture fragments",
                order_idx=0,
                points=[
                    Point(id=10, topic_id=1, text=FLYWHEEL, order_idx=0),
                    Point(id=11, topic_id=1, text=VERTICAL, order_idx=1),
                    Point(id=12, topic_id=1, text=CASE_STUDY, order_idx=2),
                    Point(id=13, topic_id=1, text=PLAIN, order_idx=3),
                ],
            )
        ],
    )


def _terse_additions() -> dict[str, object]:
    return {
        "additions": [
            {"point_id": 10, "context": FLYWHEEL_CONTEXT},
            {"point_id": 11, "context": VERTICAL_CONTEXT},
            {"point_id": 12, "context": CASE_CONTEXT},
        ]
    }


def test_enrich_leaves_raw_text_and_point_text_unchanged() -> None:
    note = _note_with_points()
    original_points = [point.text for topic in note.topics for point in topic.points]
    payload = enrich(note, complete=lambda _prompt: json.dumps(_terse_additions()))
    assert note.raw_text == RAW
    assert [point.text for topic in note.topics for point in topic.points] == original_points
    assert [item.point_id for item in payload.additions] == [10, 11, 12]
    assert all(item.context for item in payload.additions)
    assert 13 not in {item.point_id for item in payload.additions}


def test_enrich_skips_self_explanatory_point() -> None:
    note = _note_with_points()
    payload = enrich(note, complete=lambda _prompt: json.dumps(_terse_additions()))
    assert isinstance(payload, EnrichmentPayload)
    assert all(item.point_id != 13 for item in payload.additions)
    assert note.topics[0].points[3].text == PLAIN
    assert note.topics[0].points[3].context is None


def test_enrich_drops_unknown_ids_and_ignores_rewrite_keys() -> None:
    note = _note_with_points()
    payload = enrich(
        note,
        complete=lambda _prompt: json.dumps(
            {
                "additions": [
                    {
                        "point_id": 10,
                        "context": FLYWHEEL_CONTEXT,
                        "text": "REWRITTEN POINT",
                    },
                    {"point_id": 999, "context": "should be dropped"},
                ],
                "raw_text": "REWRITTEN NOTE",
            }
        ),
    )
    assert [item.point_id for item in payload.additions] == [10]
    assert note.raw_text == RAW
    assert note.topics[0].points[0].text == FLYWHEEL


def test_enrich_retries_invalid_json_once() -> None:
    replies = ["not json", json.dumps(_terse_additions())]

    def complete(_prompt: str) -> str:
        return replies.pop(0)

    payload = enrich(_note_with_points(), complete=complete)
    assert len(payload.additions) == 3
    assert replies == []


def test_enrich_raises_after_second_failure() -> None:
    with pytest.raises(EnrichmentError, match="failed validation"):
        enrich(_note_with_points(), complete=lambda _prompt: "still not json")


def test_enrich_prompt_forbids_rewrite() -> None:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"additions": []})

    enrich(_note_with_points(), complete=complete)
    assert prompts
    assert "You annotate, you do not rewrite" in prompts[0]
    assert "Do not change, rephrase, or restate" in prompts[0]


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def test_enrich_persists_additions_without_changing_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={"title": "Matsuo Lab", "source": "lecture", "raw_text": RAW},
    ).json()
    note_id = created["id"]
    replace_note_extraction(
        note_id,
        [
            ExtractedTopic(
                title="Lecture fragments",
                points=[FLYWHEEL, VERTICAL, CASE_STUDY, PLAIN],
                tags=["ai", "lecture"],
            )
        ],
    )
    note = get_note(note_id)
    assert note is not None
    original_texts = [point.text for topic in note.topics for point in topic.points]
    id_by_text = {point.text: point.id for topic in note.topics for point in topic.points}

    def complete(_prompt: str) -> str:
        return json.dumps(
            {
                "additions": [
                    {"point_id": id_by_text[FLYWHEEL], "context": FLYWHEEL_CONTEXT},
                    {"point_id": id_by_text[VERTICAL], "context": VERTICAL_CONTEXT},
                    {"point_id": id_by_text[CASE_STUDY], "context": CASE_CONTEXT},
                ]
            }
        )

    payload = enrich(note, complete=complete)
    apply_point_additions(payload.additions)
    reloaded = get_note(note_id)
    assert reloaded is not None
    assert reloaded.raw_text == RAW
    assert [point.text for topic in reloaded.topics for point in topic.points] == original_texts
    by_text = {point.text: point for topic in reloaded.topics for point in topic.points}
    assert by_text[FLYWHEEL].context == FLYWHEEL_CONTEXT
    assert by_text[FLYWHEEL].context_status == "suggested"
    assert by_text[VERTICAL].context_status == "suggested"
    assert by_text[CASE_STUDY].context_status == "suggested"
    assert by_text[PLAIN].context is None
    assert by_text[PLAIN].context_status == "none"


def test_patch_point_accept_edit_dismiss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={"title": "Matsuo Lab", "source": "lecture", "raw_text": RAW},
    ).json()
    replace_note_extraction(
        created["id"],
        [
            ExtractedTopic(
                title="Lecture fragments",
                points=[FLYWHEEL, PLAIN],
                tags=["ai", "lecture"],
            )
        ],
    )
    note = get_note(created["id"])
    assert note is not None
    flywheel = note.topics[0].points[0]
    apply_point_additions(
        [PointAddition(point_id=flywheel.id, context=FLYWHEEL_CONTEXT)]
    )

    edited = client.patch(
        f"/points/{flywheel.id}",
        json={"context": "A flywheel compounds usage into a better model."},
    )
    assert edited.status_code == 200
    assert edited.json()["text"] == FLYWHEEL
    assert edited.json()["context"] == "A flywheel compounds usage into a better model."
    assert edited.json()["context_status"] == "suggested"

    accepted = client.patch(
        f"/points/{flywheel.id}",
        json={"context_status": "accepted"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["context_status"] == "accepted"
    assert accepted.json()["text"] == FLYWHEEL

    dismissed = client.patch(
        f"/points/{flywheel.id}",
        json={"context_status": "dismissed"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["context_status"] == "dismissed"
    assert dismissed.json()["text"] == FLYWHEEL

    reopened = client.get(f"/notes/{created['id']}").json()
    assert reopened["raw_text"] == RAW
    assert reopened["topics"][0]["points"][0]["text"] == FLYWHEEL


def test_patch_point_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.patch("/points/999", json={"context_status": "accepted"}).status_code == 404
