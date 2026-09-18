from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.extract import ExtractionError, extract_topics
from app.main import app
from app.models import ExtractionPayload

SAMPLE_NOTE = """
Lecture: B+ trees in database indexes
- Leaf nodes store keys plus pointers to records
- Internal nodes only route the search
- High fanout keeps the tree short, so fewer disk I/Os than a binary tree
- Range scans walk the linked leaves
- Compared with hash indexes: B+ trees support ordered access
"""

VALID_JSON = {
    "topics": [
        {
            "title": "B+ tree structure",
            "points": [
                "Leaves hold keys and record pointers",
                "Internal nodes route searches",
            ],
            "tags": ["b-tree", "indexes"],
        },
        {
            "title": "I/O and access patterns",
            "points": [
                "High fanout reduces disk I/O",
                "Linked leaves enable range scans",
            ],
            "tags": ["disk-io", "range-scan"],
        },
    ]
}


def test_extract_topics_parses_valid_json() -> None:
    payload = extract_topics(SAMPLE_NOTE, complete=lambda _prompt: json.dumps(VALID_JSON))
    assert isinstance(payload, ExtractionPayload)
    assert len(payload.topics) == 2
    assert payload.topics[0].title == "B+ tree structure"
    assert payload.topics[1].tags == ["disk-io", "range-scan"]


def test_extract_topics_retries_invalid_json_once() -> None:
    replies = ["this is not json", json.dumps(VALID_JSON)]

    def complete(_prompt: str) -> str:
        return replies.pop(0)

    payload = extract_topics(SAMPLE_NOTE, complete=complete)
    assert len(payload.topics) == 2
    assert replies == []


def test_extract_topics_raises_after_second_failure() -> None:
    with pytest.raises(ExtractionError, match="failed validation"):
        extract_topics(SAMPLE_NOTE, complete=lambda _prompt: "still not json")


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def test_extract_endpoint_persists_and_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/notes",
        json={
            "title": "DB indexes lecture",
            "source": "lecture",
            "raw_text": SAMPLE_NOTE,
        },
    )
    note_id = created.json()["id"]

    first_payload = VALID_JSON
    second_payload = {
        "topics": [
            {
                "title": "Hash vs B+ tree",
                "points": ["Hash indexes lack ordered range scans"],
                "tags": ["hash-index", "b-tree"],
            }
        ]
    }
    replies = [json.dumps(first_payload), json.dumps(second_payload)]
    monkeypatch.setattr(
        "app.extract.chat",
        lambda messages, json_mode=False: replies.pop(0),
    )
    monkeypatch.setattr(
        "app.index.embed_texts",
        lambda texts: [[1.0] + [0.0] * 383 for _ in texts],
    )

    first = client.post(f"/notes/{note_id}/extract")
    assert first.status_code == 200
    body = first.json()
    assert len(body["topics"]) == 2
    topic = body["topics"][0]
    assert set(topic.keys()) >= {"id", "note_id", "title", "order_idx", "points", "tags"}
    assert topic["title"] == "B+ tree structure"
    assert topic["points"][0]["text"] == "Leaves hold keys and record pointers"
    assert set(topic["points"][0].keys()) >= {"id", "topic_id", "text", "order_idx"}
    assert [tag["tag"] for tag in topic["tags"]] == ["b-tree", "indexes"]
    assert set(topic["tags"][0].keys()) >= {"id", "topic_id", "tag"}

    second = client.post(f"/notes/{note_id}/extract")
    assert second.status_code == 200
    replaced = second.json()
    assert len(replaced["topics"]) == 1
    assert replaced["topics"][0]["title"] == "Hash vs B+ tree"

    reopened = client.get(f"/notes/{note_id}")
    assert len(reopened.json()["topics"]) == 1
