"""The scholarly source the Research Track resolves against: OpenAlex (default) or Semantic Scholar.

Both answer the same questions (docs/specs/research-track.md, "Components"): a work by DOI or
arXiv id, many works by id or DOI, a title search, and the works citing some others. Each
source keeps its own ids in its own Study column, so switching never mixes them up; a Study
resolved by both keeps both ids and identity merges on either.

Semantic Scholar needs the user's own S2_API_KEY (its licence forbids Atlas shipping one).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from app import openalex, research_store, s2
from app.works import Work

SourceName = Literal["openalex", "s2"]
SETTING = "scholarly_source"


@dataclass(frozen=True)
class Source:
    name: SourceName
    label: str
    id_column: Literal["openalex_id", "s2_id"]
    work_by_doi: Callable[[str], Work | None]
    work_by_arxiv: Callable[[str], Work | None]
    works_by_ids: Callable[[list[str]], dict[str, Work]]
    works_by_dois: Callable[[list[str]], dict[str, Work]]
    works_by_arxiv: Callable[[list[str]], dict[str, Work]]
    search_title: Callable[[str], list[Work]]
    citing_works: Callable[[list[str]], list[Work]]

def _openalex_by_arxiv(arxiv_ids: list[str]) -> dict[str, Work]:
    """OpenAlex knows arXiv papers by their DataCite DOI (10.48550/arxiv.<id>)."""
    by_doi = {openalex.arxiv_doi(a): a for a in arxiv_ids if openalex.arxiv_doi(a)}
    found = openalex.works_by_filter("doi", list(by_doi), "doi") if by_doi else {}
    return {by_doi[doi]: work for doi, work in found.items() if doi in by_doi}


OPENALEX = Source(
    name="openalex",
    label="OpenAlex",
    id_column="openalex_id",
    work_by_doi=openalex.work_by_doi,  # a free singleton GET, unlike a filtered batch
    work_by_arxiv=lambda a: openalex.work_by_doi(openalex.arxiv_doi(a) or ""),
    works_by_ids=lambda ids: openalex.works_by_filter("openalex_id", ids, "openalex") if ids else {},
    works_by_dois=lambda dois: openalex.works_by_filter("doi", dois, "doi") if dois else {},
    works_by_arxiv=_openalex_by_arxiv,
    search_title=openalex.search_title,
    citing_works=openalex.citing_works,
)

SEMANTIC_SCHOLAR = Source(
    name="s2",
    label="Semantic Scholar",
    id_column="s2_id",
    work_by_doi=lambda doi: next(iter(s2.works_by_dois([doi]).values()), None),
    work_by_arxiv=lambda a: s2.works_by_arxiv([a]).get(a),
    works_by_ids=s2.works_by_ids,
    works_by_dois=s2.works_by_dois,
    works_by_arxiv=s2.works_by_arxiv,
    search_title=s2.search_title,
    citing_works=s2.citing_works,
)

_SOURCES = {OPENALEX.name: OPENALEX, SEMANTIC_SCHOLAR.name: SEMANTIC_SCHOLAR}


def available() -> list[SourceName]:
    return ["openalex", "s2"] if s2.has_key() else ["openalex"]


def active() -> Source:
    """The chosen source; Semantic Scholar falls back to OpenAlex if its key is removed."""
    chosen = research_store.get_setting(SETTING, "openalex")
    if chosen == "s2" and s2.has_key():
        return SEMANTIC_SCHOLAR
    return OPENALEX


def choose(name: SourceName) -> None:
    if name not in available():
        raise ValueError(f"{name} is not available (Semantic Scholar needs S2_API_KEY in .env)")
    research_store.set_settings({SETTING: name})


def id_kwargs(source: Source, work_id: str | None) -> dict[str, str | None]:
    """{column: id} for store calls that take either source's id."""
    return {source.id_column: work_id}
