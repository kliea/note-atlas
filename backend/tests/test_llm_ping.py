from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import URLError

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_llm_ping_reachable_when_ollama_lists_model(monkeypatch: Any) -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse({"models": [{"name": "qwen2.5:3b-instruct"}]})

    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake_urlopen)

    response = client.get("/llm/ping")
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["model"] == "qwen2.5:3b-instruct"
    assert body["model_present"] is True
    assert body["error"] is None


def test_llm_ping_unreachable_when_ollama_down(monkeypatch: Any) -> None:
    def fake_urlopen(*args: object, **kwargs: object) -> BytesIO:
        raise URLError("connection refused")

    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake_urlopen)

    response = client.get("/llm/ping")
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["model_present"] is False
    assert body["error"]
