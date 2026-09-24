"""Find a Paper's Siblings and Ancestors from its Parent Papers.

Decision (docs/specs/research-track.md, "Leads"; issue #9):
- Siblings: works citing any of this Paper's Parents — Library Papers from their own reference
  lists, others from the active source (OpenAlex `cites:` or S2 citations). Rank: in the Library first → how many of this Paper's
  Parents they cite → MiniLM similarity to this Paper → recency. This Paper's own References
  are never Siblings.
- Ancestors: what this Paper's Parents cite, ranked by how many Parents cite it (convergence),
  tie-break OpenAlex `fwci` (or citation count on S2). Two hops, the second grown from the top hop-1 Ancestors. An uploaded
  Parent contributes its own Parent Papers instead of its whole reference list.
- API off: Siblings only from the Library; Ancestors only through uploaded Parents.
- Dismissed Leads are skipped here and hidden on read, so they never come back.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from app import research_store, scholarly, sources
from app.sources import Source
from app.works import Work
from app.embed import embed_texts

SIBLINGS_KEPT = 15  # 5 shown + "show more"
ANCESTORS_SHOWN = 3  # per hop; also how many hop-1 Ancestors seed hop 2
ANCESTORS_KEPT = 9  # per hop, with "show more"
HOPS = 2
_POOL = 30  # most-convergent candidates looked up per hop


@dataclass
class _Candidate:
    key: str  # OpenAlex id, or "s<id>" for a Study OpenAlex doesn't know
    study_id: int | None = None
    work: Work | None = None
    title: str = ""
    abstract: str | None = None
    year: int | None = None
    in_library: bool = False
    via: set[int] = field(default_factory=set)
    similarity: float | None = None
    fwci: float | None = None
    cited_by: int | None = None


def _key(row: sqlite3.Row, source: Source) -> str:
    """The source's id for a Study, or "s<id>" for a Study that source doesn't know."""
    return str(row[source.id_column]) if row[source.id_column] else f"s{row['id']}"


def _known(work: Work, source: Source) -> tuple[int, str] | None:
    """The Study Atlas already has for this work, if any."""
    return research_store.find_same_study(
        0, doi=work.doi, arxiv_id=work.arxiv_id, **{"openalex_id": None, **sources.id_kwargs(source, work.id)}
    )


def _materialize(candidate: _Candidate, source: Source) -> int | None:
    """The candidate's Study id, creating an API-found Lead when Atlas doesn't have it yet."""
    if candidate.study_id is not None:
        return candidate.study_id
    work = candidate.work
    if work is None or not work.title:
        return None
    known = _known(work, source)
    if known is not None:
        return known[0]
    return research_store.create_lead(
        title=work.title,
        authors=work.authors,
        year=work.year,
        venue=work.venue,
        doi=work.doi,
        oa_url=work.oa_url,
        abstract=work.abstract,
        arxiv_id=work.arxiv_id,
        **{"openalex_id": None, **sources.id_kwargs(source, work.id)},
    )


def _text(title: str, abstract: str | None) -> str:
    return f"{title}\n{abstract or ''}".strip()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _score_similarity(paper: sqlite3.Row, candidates: list[_Candidate]) -> None:
    if not candidates:
        return
    vectors = embed_texts(
        [_text(paper["title"], paper["abstract"])] + [_text(c.title, c.abstract) for c in candidates]
    )
    for candidate, vector in zip(candidates, vectors[1:]):
        candidate.similarity = round(_cosine(vectors[0], vector), 4)


# --- Siblings ------------------------------------------------------------------------


def siblings(
    paper: sqlite3.Row, parents: dict[int, sqlite3.Row], excluded: set[int], api: bool, source: Source
) -> list[_Candidate]:
    found: dict[str, _Candidate] = {}
    library = research_store.papers_citing(list(parents))
    rows = research_store.studies_by_id(set(library))
    for paper_id, cited in library.items():
        if paper_id in excluded:
            continue
        row = rows[paper_id]
        found[f"s{paper_id}"] = _Candidate(
            key=f"s{paper_id}", study_id=paper_id, title=row["title"], abstract=row["abstract"],
            year=row["year"], in_library=True, via=set(cited),
        )

    by_source_id = {row[source.id_column]: sid for sid, row in parents.items() if row[source.id_column]}
    if api and by_source_id:
        for work in source.citing_works(list(by_source_id)):
            via = {by_source_id[ref] for ref in work.referenced_works if ref in by_source_id}
            known = _known(work, source)
            if not via or (known is not None and known[0] in excluded):
                continue
            key = f"s{known[0]}" if known else work.id
            if key in found:
                found[key].via |= via
                continue
            found[key] = _Candidate(
                key=key, study_id=known[0] if known else None, work=work, title=work.title,
                abstract=work.abstract, year=work.year,
                in_library=known is not None and known[1] == "paper", via=via,
            )

    ranked = list(found.values())
    _score_similarity(paper, ranked)
    ranked.sort(
        key=lambda c: (not c.in_library, -len(c.via), -(c.similarity or 0.0), -(c.year or 0), c.key)
    )
    # Uploaded Papers are never cut; API-found Leads fill the rest.
    return [c for i, c in enumerate(ranked) if c.in_library or i < SIBLINGS_KEPT]


# --- Ancestors -----------------------------------------------------------------------


def _cited_keys(row: sqlite3.Row, api: bool, source: Source) -> set[str]:
    """What this Study contributes to Ancestors: an uploaded Paper's own Parents, else
    (API on) its OpenAlex reference list."""
    study_id = int(row["id"])
    if row["state"] == "paper" and research_store.has_parent_judgements(study_id):
        return {_key(r, source) for r in research_store.studies_by_id(research_store.parent_ids(study_id)).values()}
    if api and row[source.id_column]:
        work = source.works_by_ids([row[source.id_column]]).get(row[source.id_column])
        return set(work.referenced_works) if work else set()
    return set()


def _ancestor_hop(
    level: dict[int, sqlite3.Row], excluded_keys: set[str], excluded: set[int], api: bool, source: Source
) -> list[_Candidate]:
    counts: dict[str, set[int]] = {}
    for study_id, row in level.items():
        for key in _cited_keys(row, api, source):
            if key not in excluded_keys:
                counts.setdefault(key, set()).add(study_id)
    pool = sorted(counts, key=lambda k: (-len(counts[k]), k))[:_POOL]

    local = {int(k[1:]): k for k in pool if k.startswith("s")}
    rows = research_store.studies_by_id(set(local))
    works = source.works_by_ids([k for k in pool if not k.startswith("s")]) if api else {}
    candidates: list[_Candidate] = []
    for key in pool:
        if key.startswith("s"):
            row = rows.get(int(key[1:]))
            if row is None or int(row["id"]) in excluded:
                continue
            candidates.append(
                _Candidate(key=key, study_id=int(row["id"]), title=row["title"], year=row["year"], via=counts[key])
            )
            continue
        work = works.get(key)
        known = _known(work, source) if work else None
        if work is None or (known is not None and known[0] in excluded):
            continue
        candidates.append(
            _Candidate(
                key=key, study_id=known[0] if known else None, work=work, title=work.title,
                year=work.year, fwci=work.fwci, cited_by=work.cited_by_count, via=counts[key],
            )
        )
    # Convergence, then impact: OpenAlex's fwci where there is one, else raw citations (S2).
    candidates.sort(key=lambda c: (-len(c.via), -(c.fwci or 0.0), -(c.cited_by or 0), c.key))
    return candidates[:ANCESTORS_KEPT]


def ancestors(
    paper: sqlite3.Row, parents: dict[int, sqlite3.Row], excluded: set[int], api: bool, source: Source
) -> list[tuple[int, _Candidate]]:
    excluded_keys = {_key(paper, source), *(_key(row, source) for row in parents.values())}
    excluded_keys |= {_key(row, source) for row in research_store.studies_by_id(excluded).values()}
    out: list[tuple[int, _Candidate]] = []
    level = parents
    for hop in range(1, HOPS + 1):
        found = _ancestor_hop(level, excluded_keys, excluded, api, source)
        for candidate in found:
            candidate.study_id = _materialize(candidate, source)
        found = [c for c in found if c.study_id is not None and c.study_id not in excluded]
        out.extend((hop, c) for c in found)
        excluded_keys |= {c.key for c in found}
        excluded |= {c.study_id for c in found if c.study_id is not None}
        level = research_store.studies_by_id([c.study_id for c in found[:ANCESTORS_SHOWN] if c.study_id])
        if not level:
            break
    return out


# --- entry point ---------------------------------------------------------------------


def compute_leads(paper_id: int) -> None:
    """Recompute and store this Paper's Siblings and Ancestors.
    Raises works.BudgetExhausted / ApiError."""
    api = scholarly.api_enabled()
    source = sources.active()
    paper = research_store.studies_by_id([paper_id]).get(paper_id)
    if paper is None or paper["state"] != "paper":
        return
    parent_ids = research_store.parent_ids(paper_id)
    parents = research_store.studies_by_id(parent_ids)
    excluded = {paper_id, *parent_ids, *research_store.dismissed_ids(paper_id)}

    sibling_rows: list[dict[str, object]] = []
    for candidate in siblings(paper, parents, excluded | research_store.reference_ids(paper_id), api, source):
        study_id = _materialize(candidate, source)
        if study_id is None or study_id in excluded:
            continue
        sibling_rows.append(
            {
                "study_id": study_id,
                "kind": "sibling",
                "shared": len(candidate.via),
                "similarity": candidate.similarity,
                "via": sorted(candidate.via),
            }
        )
    excluded |= {int(row["study_id"]) for row in sibling_rows}  # type: ignore[arg-type]

    ancestor_rows: list[dict[str, object]] = [
        {
            "study_id": candidate.study_id,
            "kind": "ancestor",
            "hop": hop,
            "shared": len(candidate.via),
            "fwci": candidate.fwci,
            "via": sorted(candidate.via),
        }
        for hop, candidate in ancestors(paper, parents, set(excluded), api, source)
    ]
    research_store.replace_paper_leads(paper_id, sibling_rows + ancestor_rows)
