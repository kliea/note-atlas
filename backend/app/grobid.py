"""GROBID sidecar: parse a PDF over localhost, starting the container on demand.

GROBID runs as the CRF Docker image bound to 127.0.0.1. Atlas starts it only when
an upload needs it and stops it once the research queue has been idle, and only
if Atlas was the one that started it. Crossref consolidation is always off so
nothing leaves the machine.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time

import httpx

from app.config import grobid_autostart, grobid_image, grobid_url

CONTAINER_NAME = "atlas-grobid"
_START_TIMEOUT_SECONDS = 90.0
_PARSE_TIMEOUT_SECONDS = 300.0
_PARSE_FIELDS = {
    "consolidateHeader": "0",
    "consolidateCitations": "0",
    "includeRawCitations": "1",
    "segmentSentences": "1",
}


class GrobidUnavailable(RuntimeError):
    """GROBID could not be reached or started."""


_lock = threading.Lock()
_started_by_atlas = False


def is_alive() -> bool:
    try:
        response = httpx.get(f"{grobid_url()}/api/isalive", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200 and response.text.strip() == "true"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=60, check=False
    )


def _atlas_container_running() -> bool:
    if shutil.which("docker") is None:
        return False
    result = _docker("ps", "-q", "--filter", f"name=^{CONTAINER_NAME}$")
    return result.returncode == 0 and bool(result.stdout.strip())


def ensure_running() -> None:
    """Make GROBID reachable, starting the container if allowed. Raises GrobidUnavailable."""
    global _started_by_atlas
    with _lock:
        if is_alive():
            return
        if not grobid_autostart():
            raise GrobidUnavailable("GROBID is not running and autostart is off")
        if shutil.which("docker") is None:
            raise GrobidUnavailable("docker is not installed")
        running = _docker("ps", "-q", "--filter", f"name=^{CONTAINER_NAME}$")
        if running.returncode != 0:
            raise GrobidUnavailable(f"docker is not available: {running.stderr.strip()}")
        if not running.stdout.strip():
            started = _docker(
                "run", "-d", "--rm", "--init",
                "--name", CONTAINER_NAME,
                "-p", "127.0.0.1:8070:8070",
                grobid_image(),
            )
            if started.returncode != 0:
                raise GrobidUnavailable(f"could not start GROBID: {started.stderr.strip()}")
            _started_by_atlas = True
        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if is_alive():
                return
            time.sleep(1.0)
        raise GrobidUnavailable("GROBID did not become ready in time")


def stop_if_started() -> None:
    """Stop the container only if Atlas started it.

    A container under Atlas's name counts as Atlas's even when an earlier process
    started it, so a crash or restart never leaves GROBID running indefinitely.
    """
    global _started_by_atlas
    with _lock:
        if not _started_by_atlas and not _atlas_container_running():
            return
        _docker("stop", CONTAINER_NAME)
        _started_by_atlas = False


def process_fulltext(pdf_bytes: bytes) -> str:
    """Return GROBID's TEI XML for a PDF. Raises GrobidUnavailable."""
    ensure_running()
    try:
        response = httpx.post(
            f"{grobid_url()}/api/processFulltextDocument",
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            data=_PARSE_FIELDS,
            timeout=_PARSE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise GrobidUnavailable(f"GROBID request failed: {exc}") from exc
    if response.status_code != 200:
        raise GrobidUnavailable(f"GROBID returned HTTP {response.status_code}")
    return response.text
