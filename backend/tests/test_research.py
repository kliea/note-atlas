"""Research Track slice 1: upload → parse → Paper in the Library, with GROBID faked."""

from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import grobid, paper_extract, research_jobs, research_store
from app.db import get_connection, init_db, migrate_down
from app.main import app
from app.tei import parse_tei

TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:xml="http://www.w3.org/XML/1998/namespace">
  <teiHeader>
    <fileDesc>
      <titleStmt><title level="a" type="main">Lost in the Middle</title></titleStmt>
      <sourceDesc><biblStruct><analytic>
        <author><persName><forename type="first">Nelson</forename><forename type="middle">F</forename><surname>Liu</surname></persName></author>
        <author><persName><forename type="first">Percy</forename><surname>Liang</surname></persName></author>
        <idno type="DOI">10.1162/tacl_a_00638</idno>
      </analytic><monogr><imprint><date type="published" when="2023-07-06"/></imprint></monogr></biblStruct></sourceDesc>
    </fileDesc>
    <profileDesc><abstract><p>Models struggle with the middle of long contexts.</p></abstract></profileDesc>
  </teiHeader>
  <text>
    <body>
      <div><head>Introduction</head>
        <p><s>We extend <ref type="bibr" target="#b0">[1]</ref> to long inputs.</s>
           <s>Retrieval follows <ref type="bibr" target="#b1">[2]</ref> and <ref type="bibr" target="#b0">[1]</ref>.</s></p>
      </div>
      <div><head>Acknowledgements</head>
        <p><s>Thanks to <ref type="bibr" target="#b1">[2]</ref>.</s></p>
      </div>
    </body>
    <back><div type="references"><listBibl>
      <biblStruct xml:id="b0">
        <analytic><title level="a" type="main">Sharp Nearby, Fuzzy Far Away</title>
          <author><persName><forename type="first">Urvashi</forename><surname>Khandelwal</surname></persName></author>
          <idno type="arXiv">1805.04623</idno></analytic>
        <monogr><title level="m">ACL</title><imprint><date type="published" when="2018"/></imprint></monogr>
        <note type="raw_reference">Khandelwal et al. Sharp Nearby, Fuzzy Far Away. ACL 2018.</note>
      </biblStruct>
      <biblStruct xml:id="b1">
        <monogr><title level="m">Speech and Language Processing</title>
          <author><persName><forename type="first">Dan</forename><surname>Jurafsky</surname></persName></author>
          <imprint><date type="published" when="2009"/></imprint></monogr>
        <note type="raw_reference">Jurafsky. Speech and Language Processing. 2009.</note>
      </biblStruct>
    </listBibl></div></back>
  </text>
</TEI>
"""


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


FIELDS = paper_extract.ExtractedFields(
    research_question="How do models use long contexts?",
    contributions=["A controlled multi-document QA benchmark.", "Evidence that extended context doesn't help."],
    method="Vary the position of the relevant document.",
    key_results="Accuracy drops >20 points in the middle.",
    scope="2023 decoder LMs, contexts up to 16K tokens.",
)
LIMITATION = paper_extract.LimitationCandidate(
    text="Only 2023 models were evaluated.", quote="we leave newer models to future work"
)


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Never call Ollama; record which extraction steps ran."""
    calls: list[str] = []

    def fields(_title: str, _abstract: str, _body: str) -> paper_extract.ExtractedFields:
        calls.append("fields")
        return FIELDS

    def limitations(_body: str, _text: str) -> list[paper_extract.LimitationCandidate]:
        calls.append("limitations")
        return [LIMITATION]

    monkeypatch.setattr(paper_extract, "extract_fields", fields)
    monkeypatch.setattr(paper_extract, "extract_limitations", limitations)
    return calls


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    return TestClient(app)


def _upload(client: TestClient, *names: str) -> list[dict]:
    files = [("files", (name, _pdf_bytes(), "application/pdf")) for name in names]
    response = client.post("/research/papers", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def _drain() -> None:
    while research_jobs.process_next_job():
        pass


# --- TEI parsing ------------------------------------------------------------------


def test_parse_tei_metadata_references_and_mentions() -> None:
    parsed = parse_tei(TEI)
    assert parsed.title == "Lost in the Middle"
    assert parsed.authors == ["Nelson F Liu", "Percy Liang"]
    assert parsed.year == 2023
    assert parsed.doi == "10.1162/tacl_a_00638"
    assert "middle of long contexts" in parsed.abstract
    assert [s.head for s in parsed.sections] == ["Introduction"]

    sharp, book = parsed.references
    assert sharp.title == "Sharp Nearby, Fuzzy Far Away"
    assert sharp.authors == ["Urvashi Khandelwal"]
    assert (sharp.year, sharp.arxiv_id, sharp.venue) == (2018, "1805.04623", "ACL")
    assert sharp.mention_count == 2
    assert sharp.contexts[0] == {"section": "Introduction", "sentence": "We extend [1] to long inputs."}
    # A book has no analytic title; the monograph title is the title. Acknowledgement mentions don't count.
    assert (book.title, book.venue, book.mention_count) == ("Speech and Language Processing", None, 1)
    assert book.raw.startswith("Jurafsky")


# --- schema --------------------------------------------------------------------------


def test_migration_v6_creates_and_drops_research_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notes.db"))
    init_db()
    tables = {"studies", "cites", "claims", "lead_dismissals", "research_jobs", "research_settings"}
    conn = get_connection()
    try:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables <= names
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO studies (state, title, created_at) VALUES ('draft', 't', 'now')")
        migrate_down(5, conn)
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not (tables & names)
    finally:
        conn.close()


# --- upload → parse ------------------------------------------------------------------


def test_upload_rejects_non_pdf(client: TestClient) -> None:
    response = client.post("/research/papers", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert response.status_code == 400
    assert "not a PDF" in response.json()["detail"]
    assert client.get("/research/studies").json() == []


def test_upload_then_parse_turns_references_into_leads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    (created,) = _upload(client, "liu2023.pdf")
    assert created["state"] == "paper"
    assert created["title"] == "liu2023"
    assert created["job"] == {"status": "queued", "step": "parse", "error": None, "queue_position": 1}
    assert research_store.pdf_path(created["id"]).read_bytes().startswith(b"%PDF")

    _drain()

    study = client.get(f"/research/studies/{created['id']}").json()
    assert study["title"] == "Lost in the Middle"
    assert study["authors"] == ["Nelson F Liu", "Percy Liang"]
    assert study["year"] == 2023
    assert study["reference_count"] == 2
    assert study["references_status"] == "ok"
    assert study["job"]["status"] == "done"
    assert [(r["title"], r["state"], r["mention_count"]) for r in study["references"]] == [
        ("Sharp Nearby, Fuzzy Far Away", "lead", 2),
        ("Speech and Language Processing", "lead", 1),
    ]
    assert research_store.pdf_path(created["id"]).with_suffix(".tei.xml").exists()

    leads = client.get("/research/studies", params={"state": "lead"}).json()
    assert {lead["title"] for lead in leads} == {"Sharp Nearby, Fuzzy Far Away", "Speech and Language Processing"}
    papers = client.get("/research/studies", params={"state": "paper", "q": "middle"}).json()
    assert [p["id"] for p in papers] == [created["id"]]


def test_reparse_does_not_duplicate_leads(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    (created,) = _upload(client, "a.pdf")
    _drain()
    research_store.apply_parse(created["id"], parse_tei(TEI))
    assert len(client.get("/research/studies", params={"state": "lead"}).json()) == 2


def test_grobid_unavailable_falls_back_to_text_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(_pdf: bytes) -> str:
        raise grobid.GrobidUnavailable("docker is not installed")

    monkeypatch.setattr(grobid, "process_fulltext", unavailable)
    (created,) = _upload(client, "scan.pdf")
    _drain()

    study = client.get(f"/research/studies/{created['id']}").json()
    assert study["title"] == "scan"
    assert study["references_status"] == "unavailable"
    assert study["reference_count"] == 0
    assert research_store.pdf_path(created["id"]).with_suffix(".txt").exists()
    # The blank test PDF has no text layer, so extraction fails with a clear reason.
    assert study["job"]["status"] == "failed"
    assert study["job"]["step"] == "extract"
    assert "no text could be read" in study["job"]["error"]


# --- queue ---------------------------------------------------------------------------


def test_batch_queues_fifo_with_positions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    first, second, third = _upload(client, "one.pdf", "two.pdf", "three.pdf")
    assert [s["job"]["queue_position"] for s in (first, second, third)] == [1, 2, 3]

    assert research_jobs.process_next_job() is True
    by_id = {s["id"]: s for s in client.get("/research/studies", params={"state": "paper"}).json()}
    assert by_id[first["id"]]["job"]["status"] == "done"
    assert by_id[second["id"]]["job"]["queue_position"] == 1
    assert by_id[third["id"]]["job"]["queue_position"] == 2


def test_interrupted_job_resumes_after_restart(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    (created,) = _upload(client, "a.pdf")
    # A previous process claimed the job and died mid-step.
    assert research_store.claim_next_job() is not None
    assert research_jobs.process_next_job() is False

    assert research_store.reset_interrupted_jobs() == 1
    assert research_jobs.process_next_job() is True
    assert client.get(f"/research/studies/{created['id']}").json()["job"]["status"] == "done"


def test_failed_step_can_be_retried(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_pdf: bytes) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(grobid, "process_fulltext", broken)
    (created,) = _upload(client, "a.pdf")
    _drain()
    job = client.get(f"/research/studies/{created['id']}").json()["job"]
    assert job["status"] == "failed"
    assert job["step"] == "parse"
    assert "boom" in job["error"]

    monkeypatch.setattr(grobid, "process_fulltext", lambda _pdf: TEI)
    retried = client.post(f"/research/studies/{created['id']}/retry")
    assert retried.json()["job"]["status"] == "queued"
    _drain()
    assert client.get(f"/research/studies/{created['id']}").json()["job"]["status"] == "done"
    assert client.post(f"/research/studies/{created['id']}/retry").status_code == 409


# --- GROBID on demand ---------------------------------------------------------------


class _FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.alive = False

    def __call__(self, *args: str):
        self.calls.append(args)
        if args[0] == "run":
            self.alive = True
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def test_grobid_started_on_demand_and_stopped_only_if_atlas_started_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker = _FakeDocker()
    monkeypatch.setattr(grobid, "_docker", docker)
    monkeypatch.setattr(grobid, "is_alive", lambda: docker.alive)
    monkeypatch.setattr(grobid.shutil, "which", lambda _name: "/usr/local/bin/docker")
    monkeypatch.setattr(grobid, "_started_by_atlas", False)

    grobid.ensure_running()
    run = next(c for c in docker.calls if c[0] == "run")
    assert "127.0.0.1:8070:8070" in run
    grobid.stop_if_started()
    assert docker.calls[-1] == ("stop", grobid.CONTAINER_NAME)

    # Already running under another name (e.g. the user started it): never started or stopped by Atlas.
    docker.calls.clear()
    grobid.ensure_running()
    grobid.stop_if_started()
    assert not any(call[0] in ("run", "stop") for call in docker.calls)


def test_grobid_left_by_a_crashed_process_is_still_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str):
        calls.append(args)
        stdout = "abc123\n" if args[0] == "ps" else ""
        return type("Done", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr(grobid, "_docker", docker)
    monkeypatch.setattr(grobid.shutil, "which", lambda _name: "/usr/local/bin/docker")
    monkeypatch.setattr(grobid, "_started_by_atlas", False)
    grobid.stop_if_started()
    assert calls[-1] == ("stop", grobid.CONTAINER_NAME)


def test_grobid_autostart_off_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grobid, "is_alive", lambda: False)
    monkeypatch.setenv("GROBID_AUTOSTART", "0")
    with pytest.raises(grobid.GrobidUnavailable):
        grobid.ensure_running()
