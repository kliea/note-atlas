"""Optional Semantic Scholar influence signals, only with the user's own S2_API_KEY.

S2's licence forbids sharing a key, so Atlas never ships one. Given a Paper's DOI, this
returns which of its References S2 flags as influential and why they were cited. The
signal is sparse, so it only boosts the shortlist; it never decides Parents alone.
"""

from __future__ import annotations

import json
import logging

import httpx

from app import research_store, scholarly
from app.config import s2_api_key
from app.openalex import USER_AGENT, normalize_doi
from app.paper_extract import normalize

log = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
_TIMEOUT_SECONDS = 20.0
_FIELDS = "isInfluential,intents,citedPaper.title,citedPaper.externalIds"


def reference_signals(paper_doi: str | None) -> dict[str, tuple[bool, list[str]]]:
    """{normalized DOI or title: (is_influential, intents)}; empty without a key, with the
    scholarly API switched off, or on any failure."""
    key = s2_api_key()
    doi = normalize_doi(paper_doi)
    if not key or not doi or not scholarly.api_enabled():
        return {}
    cache_key = f"s2refs:{doi}"
    body = research_store.cache_get(cache_key)
    if body is None:
        try:
            response = httpx.get(
                f"{BASE_URL}/paper/DOI:{doi}/references",
                params={"fields": _FIELDS, "limit": "1000"},
                headers={"x-api-key": key, "User-Agent": USER_AGENT},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            log.warning("Semantic Scholar unreachable: %s", exc)
            return {}
        if response.status_code != 200:
            log.warning("Semantic Scholar returned HTTP %s", response.status_code)
            return {}
        body = response.text
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
