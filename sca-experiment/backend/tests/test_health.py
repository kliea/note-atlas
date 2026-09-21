from app.main import Health, NoteIn


def test_health_model() -> None:
    payload = Health(status="ok", embed_model="all-MiniLM-L6-v2")
    assert payload.status == "ok"


def test_note_defaults() -> None:
    note = NoteIn(title="fixture")
    assert note.body is None
