"""Crossref title→DOI fallback for References OpenAlex didn't link.

Free and outside OpenAlex's budget. Sends only the reference's title (plus first
author surname and year to disambiguate). A `mailto` is sent only if the user set
CROSSREF_MAILTO. Results are cached by normalized title.
"""

from __future__ import annotations

import json

import httpx

from app import research_store
from app.config import crossref_mailto
from app.openalex import USER_AGENT, normalize_doi

BASE_URL = "https://api.crossref.org"
_TIMEOUT_SECONDS = 20.0


class CrossrefError(RuntimeError):
    pass


def lookup(title: str, author: str | None, year: int | None) -> list[dict[str, object]]:
    """Top candidates as {doi, title, year}. Raises CrossrefError on failure."""
    key = f"crossref:{' '.join(title.lower().split())}|{year or ''}"
    cached = research_store.cache_get(key)
    if cached is not None:
        return json.loads(cached)
    bibliographic = " ".join(part for part in (title, author or "", str(year or "")) if part)
    params = {"query.bibliographic": bibliographic, "rows": "3", "select": "DOI,title,issued"}
    mailto = crossref_mailto()
    if mailto:
        params["mailto"] = mailto
    try:
        response = httpx.get(
            f"{BASE_URL}/works",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise CrossrefError(f"Crossref unreachable: {exc}") from exc
    if response.status_code != 200:
        raise CrossrefError(f"Crossref returned HTTP {response.status_code}")
    candidates: list[dict[str, object]] = []
    for item in response.json().get("message", {}).get("items", []):
        parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
        candidates.append(
            {
                "doi": normalize_doi(item.get("DOI")),
                "title": " ".join(item.get("title") or []),
                "year": parts[0] if parts else None,
            }
        )
    research_store.cache_put({key: json.dumps(candidates)})
    return candidates
