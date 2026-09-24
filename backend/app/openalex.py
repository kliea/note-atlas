"""OpenAlex client: resolve Studies to canonical works, cached, within the daily budget.

Only identifiers and titles are sent — never PDFs, Extractions, or notes. Every work
record is cached in SQLite by OpenAlex id and DOI, so repeat lookups cost nothing.
Budget headers are recorded for the Research Track's status pill; a 429 raises
BudgetExhausted with the time the budget resets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import research_store
from app.config import openalex_api_key

BASE_URL = "https://api.openalex.org"
USER_AGENT = "NoteAtlas/0.1"
_TIMEOUT_SECONDS = 20.0
_BATCH = 100
_SELECT = ",".join(
    (
        "id", "doi", "title", "publication_year", "authorships", "primary_location",
        "best_oa_location", "open_access", "referenced_works", "ids", "fwci", "cited_by_count",
    )
)


class ApiError(RuntimeError):
    """OpenAlex failed for a reason other than the budget."""


class BudgetExhausted(RuntimeError):
    def __init__(self, reset_at: datetime) -> None:
        super().__init__(f"OpenAlex daily budget exhausted until {reset_at.isoformat()}")
        self.reset_at = reset_at


@dataclass
class Work:
    openalex_id: str
    doi: str | None
    title: str
    year: int | None
    authors: list[str]
    venue: str | None
    oa_url: str | None
    referenced_works: list[str]


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi or None


def arxiv_doi(arxiv_id: str | None) -> str | None:
    """arXiv's DataCite DOI, 10.48550/arxiv.<id>, with any version suffix dropped."""
    if not arxiv_id:
        return None
    bare = re.sub(r"v\d+$", "", arxiv_id.strip().lower().removeprefix("arxiv:"))
    return f"10.48550/arxiv.{bare}" if bare else None


def short_id(openalex_id: str) -> str:
    return openalex_id.rsplit("/", 1)[-1]


def _work(data: dict[str, Any]) -> Work:
    location = data.get("primary_location") or {}
    source = location.get("source") or {}
    best = data.get("best_oa_location") or {}
    open_access = data.get("open_access") or {}
    return Work(
        openalex_id=short_id(str(data.get("id", ""))),
        doi=normalize_doi(data.get("doi")),
        title=str(data.get("title") or ""),
        year=data.get("publication_year"),
        authors=[
            str((a.get("author") or {}).get("display_name", ""))
            for a in data.get("authorships") or []
            if (a.get("author") or {}).get("display_name")
        ],
        venue=source.get("display_name"),
        oa_url=best.get("pdf_url") or open_access.get("oa_url"),
        referenced_works=[short_id(w) for w in data.get("referenced_works") or []],
    )


def _reset_at(response: httpx.Response) -> datetime:
    now = datetime.now(timezone.utc)
    for header in ("retry-after", "x-ratelimit-reset"):
        value = response.headers.get(header)
        if value and value.strip().isdigit():
            return now + timedelta(seconds=int(value))
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)


def _record_budget(response: httpx.Response) -> None:
    headers = response.headers
    values: dict[str, str] = {}
    if "x-ratelimit-remaining-usd" in headers:
        values["openalex_remaining_usd"] = headers["x-ratelimit-remaining-usd"]
    if "x-ratelimit-limit-usd" in headers:
        values["openalex_limit_usd"] = headers["x-ratelimit-limit-usd"]
    if values:
        values["openalex_reset_at"] = _reset_at(response).isoformat()
        research_store.set_settings(values)


def _get(path: str, params: dict[str, str]) -> dict[str, Any] | None:
    """GET from OpenAlex. Returns None for 404. Raises BudgetExhausted or ApiError."""
    query = dict(params)
    key = openalex_api_key()
    if key:
        query["api_key"] = key
    try:
        response = httpx.get(
            f"{BASE_URL}{path}",
            params=query,
            headers={"User-Agent": USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ApiError(f"OpenAlex unreachable: {exc}") from exc
    _record_budget(response)
    if response.status_code == 429:
        reset_at = _reset_at(response)
        research_store.set_settings(
            {"openalex_remaining_usd": "0", "openalex_reset_at": reset_at.isoformat()}
        )
        raise BudgetExhausted(reset_at)
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ApiError(f"OpenAlex returned HTTP {response.status_code}")
    return response.json()


def _cache(data: dict[str, Any]) -> Work:
    work = _work(data)
    body = json.dumps(data)
    entries = {f"openalex:{work.openalex_id}": body}
    if work.doi:
        entries[f"doi:{work.doi}"] = body
    research_store.cache_put(entries)
    return work


def _cached(key: str) -> Work | None:
    body = research_store.cache_get(key)
    return _work(json.loads(body)) if body else None


def work_by_doi(doi: str) -> Work | None:
    """Free singleton lookup."""
    doi = normalize_doi(doi) or ""
    if not doi:
        return None
    cached = _cached(f"doi:{doi}")
    if cached:
        return cached
    data = _get(f"/works/doi:{doi}", {"select": _SELECT})
    return _cache(data) if data else None


def works_by_filter(field: str, values: list[str], cache_prefix: str) -> dict[str, Work]:
    """Batch lookup by openalex_id or doi ($0.0001 per 100). Returns {value: Work}."""
    found: dict[str, Work] = {}
    missing: list[str] = []
    for value in values:
        cached = _cached(f"{cache_prefix}:{value}")
        if cached:
            found[value] = cached
        else:
            missing.append(value)
    for start in range(0, len(missing), _BATCH):
        batch = missing[start : start + _BATCH]
        data = _get(
            "/works",
            {"filter": f"{field}:{'|'.join(batch)}", "select": _SELECT, "per_page": str(_BATCH)},
        )
        for item in (data or {}).get("results", []):
            work = _cache(item)
            key = work.openalex_id if cache_prefix == "openalex" else work.doi
            if key:
                found[key] = work
    return found


def search_title(title: str) -> list[Work]:
    """Title search ($0.001). Used only for the Paper itself when it has no DOI or arXiv id."""
    cleaned = " ".join(title.replace(",", " ").split())
    if not cleaned:
        return []
    data = _get(
        "/works", {"filter": f"title.search:{cleaned}", "select": _SELECT, "per_page": "5"}
    )
    return [_cache(item) for item in (data or {}).get("results", [])]


def budget() -> dict[str, str | None]:
    return {
        "remaining_usd": research_store.get_setting("openalex_remaining_usd"),
        "limit_usd": research_store.get_setting("openalex_limit_usd"),
        "reset_at": research_store.get_setting("openalex_reset_at"),
    }
