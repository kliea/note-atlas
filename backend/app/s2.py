"""Semantic Scholar (S2) Academic Graph client, only with the user's own S2_API_KEY.

S2's licence forbids sharing a key, so Atlas never ships one. With a key, S2 serves two roles:
- Influence signals for Parent selection (`reference_signals`), whichever source is active.
- A full alternative to OpenAlex (see `app.sources`): resolve Papers and References, their
  reference lists (Ancestors), and the works citing a Parent (Siblings).

Keys start at 1 request/second, so every call waits its turn; a 429 is retried with backoff
and, if it persists, pauses network work like OpenAlex's spent budget does. Only titles and
identifiers are sent. Responses are cached in SQLite.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import research_store
from app.config import s2_api_key
from app.openalex import USER_AGENT, normalize_doi
from app.paper_extract import normalize
from app.works import ApiError, BudgetExhausted, Work

log = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
SOURCE_NAME = "Semantic Scholar"
MIN_INTERVAL_SECONDS = 1.05  # keys start at 1 request/second
_RETRIES = 3
_RATE_LIMIT_PAUSE = timedelta(minutes=1)
_TIMEOUT_SECONDS = 20.0
_BATCH = 500
_CITING_LIMIT = 100
_SIGNAL_FIELDS = "isInfluential,intents,citedPaper.title,citedPaper.externalIds"
_PAPER_FIELDS = "paperId,externalIds,title,year,authors,venue,openAccessPdf,abstract,citationCount"
_WORK_FIELDS = f"{_PAPER_FIELDS},references.paperId"

_lock = threading.Lock()
_last_call = 0.0


def has_key() -> bool:
    return bool(s2_api_key())


def _wait_turn() -> None:
    global _last_call
    with _lock:
        wait = _last_call + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _request(method: str, path: str, *, params: dict[str, str], body: Any = None) -> Any | None:
    """Call S2. None on 404. Raises ApiError, or BudgetExhausted when it keeps rate-limiting."""
    key = s2_api_key()
    if not key:
        raise ApiError("Semantic Scholar needs your own S2_API_KEY in .env")
    headers = {"x-api-key": key, "User-Agent": USER_AGENT}
    for attempt in range(_RETRIES):
        _wait_turn()
        try:
            if method == "GET":
                response = httpx.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=_TIMEOUT_SECONDS)
            else:
                response = httpx.post(
                    f"{BASE_URL}{path}", params=params, json=body, headers=headers, timeout=_TIMEOUT_SECONDS
                )
        except httpx.HTTPError as exc:
            raise ApiError(f"Semantic Scholar unreachable: {exc}") from exc
        if response.status_code == 429:
            time.sleep(MIN_INTERVAL_SECONDS * 2**attempt)
            continue
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ApiError(f"Semantic Scholar returned HTTP {response.status_code}")
        return json.loads(response.text)
    raise BudgetExhausted(datetime.now(timezone.utc) + _RATE_LIMIT_PAUSE, source=SOURCE_NAME)


# --- influence signals (Parent selection) ----------------------------------------------


def reference_signals(paper_doi: str | None) -> dict[str, tuple[bool, list[str]]]:
    """{normalized DOI or title: (is_influential, intents)}; empty without a key, with the
    scholarly API switched off, or on any failure. It only ever boosts the shortlist."""
    doi = normalize_doi(paper_doi)
    if not has_key() or not doi or research_store.get_setting("scholarly_api", "on") == "off":
        return {}
    cache_key = f"s2refs:{doi}"
    body = research_store.cache_get(cache_key)
    if body is None:
        try:
            data = _request("GET", f"/paper/DOI:{doi}/references", params={"fields": _SIGNAL_FIELDS, "limit": "1000"})
        except (ApiError, BudgetExhausted) as exc:
            log.warning("Semantic Scholar signals unavailable: %s", exc)
            return {}
        if data is None:
            return {}
        body = json.dumps(data)
        research_store.cache_put({cache_key: body})
    signals: dict[str, tuple[bool, list[str]]] = {}
    for item in json.loads(body).get("data", []):
        cited = item.get("citedPaper") or {}
        value = (bool(item.get("isInfluential")), [str(i) for i in item.get("intents") or []])
        ref_doi = normalize_doi((cited.get("externalIds") or {}).get("DOI"))
        if ref_doi:
            signals[f"doi:{ref_doi}"] = value
        if cited.get("title"):
            signals[f"title:{normalize(cited['title'])}"] = value
    return signals


# --- works (S2 as the active source) ---------------------------------------------------


def _work(data: dict[str, Any]) -> Work:
    ext = data.get("externalIds") or {}
    return Work(
        id=str(data["paperId"]),
        doi=normalize_doi(ext.get("DOI")),
        title=str(data.get("title") or ""),
        year=data.get("year"),
        authors=[str(a["name"]) for a in data.get("authors") or [] if a.get("name")],
        venue=data.get("venue") or None,
        oa_url=(data.get("openAccessPdf") or {}).get("url") or None,
        referenced_works=[str(r["paperId"]) for r in data.get("references") or [] if r.get("paperId")],
        abstract=data.get("abstract"),
        arxiv_id=ext.get("ArXiv"),
        cited_by_count=data.get("citationCount"),
    )


def _cache(data: dict[str, Any]) -> Work:
    work = _work(data)
    body = json.dumps(data)
    entries = {f"s2:{work.id}": body}
    if work.doi:
        entries[f"s2doi:{work.doi}"] = body
    if work.arxiv_id:
        entries[f"s2arxiv:{work.arxiv_id.lower()}"] = body
    research_store.cache_put(entries)
    return work


def _cached(key: str) -> Work | None:
    body = research_store.cache_get(key)
    return _work(json.loads(body)) if body else None


def _batch(prefix: str, cache_prefix: str, values: list[str]) -> dict[str, Work]:
    """Look up many papers by one kind of id (paperId, DOI:, ARXIV:); {value: Work}."""
    found: dict[str, Work] = {}
    missing: list[str] = []
    for value in dict.fromkeys(v for v in values if v):
        cached = _cached(f"{cache_prefix}:{value.lower() if cache_prefix != 's2' else value}")
        if cached:
            found[value] = cached
        else:
            missing.append(value)
    for start in range(0, len(missing), _BATCH):
        chunk = missing[start : start + _BATCH]
        data = _request("POST", "/paper/batch", params={"fields": _WORK_FIELDS}, body={"ids": [f"{prefix}{v}" for v in chunk]})
        for value, item in zip(chunk, data or [], strict=False):
            if item and item.get("paperId"):
                found[value] = _cache(item)
    return found


def works_by_ids(ids: list[str]) -> dict[str, Work]:
    return _batch("", "s2", ids)


def works_by_dois(dois: list[str]) -> dict[str, Work]:
    normalized = [d for d in (normalize_doi(d) for d in dois) if d]
    return _batch("DOI:", "s2doi", normalized)


def works_by_arxiv(arxiv_ids: list[str]) -> dict[str, Work]:
    return _batch("ARXIV:", "s2arxiv", arxiv_ids)


def search_title(title: str) -> list[Work]:
    """S2's single closest title match (or nothing)."""
    cleaned = " ".join(title.split())
    if not cleaned:
        return []
    data = _request("GET", "/paper/search/match", params={"query": cleaned, "fields": _WORK_FIELDS})
    items = (data or {}).get("data") or []
    return [_cache(item) for item in items if item.get("paperId")]


def citing_works(ids: list[str], limit: int = _CITING_LIMIT) -> list[Work]:
    """Works citing any of these papers. Each Work's `referenced_works` lists which of these
    ids it cites, which is all Sibling ranking needs (S2 citations aren't sortable by impact)."""
    out: dict[str, Work] = {}
    for paper_id in dict.fromkeys(i for i in ids if i):
        key = f"s2citing:{paper_id}:{limit}"
        body = research_store.cache_get(key)
        if body is None:
            fields = ",".join(f"citingPaper.{f}" for f in _PAPER_FIELDS.split(","))
            data = _request("GET", f"/paper/{paper_id}/citations", params={"fields": fields, "limit": str(limit)})
            body = json.dumps((data or {}).get("data") or [])
            research_store.cache_put({key: body})
        for item in json.loads(body):
            citing = item.get("citingPaper") or {}
            if not citing.get("paperId"):
                continue
            work = out.get(citing["paperId"]) or _work(citing)
            if paper_id not in work.referenced_works:
                work.referenced_works.append(paper_id)
            out[work.id] = work
    return list(out.values())
