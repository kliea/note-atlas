"""Default tests skip the ambient extraction job so they never call Ollama."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "ambient: run the background extraction job with mocks"
    )
    config.addinivalue_line(
        "markers", "real_parents: run Parent selection instead of the no-op stand-in"
    )


@pytest.fixture(autouse=True)
def _silence_ambient(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("ambient"):
        return
    monkeypatch.setattr("app.ambient.run_extraction_job", lambda _note_id: None)
    monkeypatch.setattr("app.ambient.run_enrichment_job", lambda _note_id: None)


@pytest.fixture(autouse=True)
def _silence_parent_selection(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Research pipeline tests never reach Ollama through the Parents step."""
    if request.node.get_closest_marker("real_parents"):
        return
    monkeypatch.setattr("app.paper_parents.choose_parents", lambda *_args, **_kwargs: {})
