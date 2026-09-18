from __future__ import annotations

import json

import pytest

from app.models import RephrasedNote
from app.rephrase import RephraseError, rephrase_jot

VALID = {"title": "B+ tree fanout", "body": "High fanout keeps the tree shallow and cuts disk I/O."}


def test_rephrase_jot_parses_json() -> None:
    result = rephrase_jot(
        "fanout high = less disk io",
        title="fanout",
        complete=lambda _prompt: json.dumps(VALID),
    )
    assert result == RephrasedNote(
        title="B+ tree fanout",
        body="High fanout keeps the tree shallow and cuts disk I/O.",
    )


def test_rephrase_jot_retries_after_bad_json() -> None:
    replies = ["not json", json.dumps(VALID)]

    def complete(_prompt: str) -> str:
        return replies.pop(0)

    result = rephrase_jot("jot", complete=complete)
    assert result.title == "B+ tree fanout"
    assert replies == []


def test_rephrase_jot_raises_after_two_failures() -> None:
    with pytest.raises(RephraseError):
        rephrase_jot("jot", complete=lambda _prompt: "still broken")
