"""Resolve a Paper and its References to canonical works, and settle Study identity.

Order of lookups keeps cost low (docs/specs/research-track.md, "Leads"; issue #18):
1. The Paper: DOI → arXiv DOI (both free) → title search ($0.001) only as a last resort.
2. Its References: match against the Paper's own `referenced_works` (one batch), then batch
   DOI/arXiv lookups, then Crossref title→DOI (free) for the rest.
Strong identifiers (DOI, arXiv, OpenAlex id) merge Studies automatically; a close title
alone only suggests a match for the user to confirm.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from difflib import SequenceMatcher

from app import crossref, openalex, research_store
from app.paper_extract import normalize

log = logging.getLogger(__name__)

TITLE_MATCH = 0.9
_MIN_TITLE_CHARS = 12
# A title cut before its subtitle ("Sharp Nearby, Fuzzy Far Away" vs "...: How Neural LMs Use Context").
_MIN_PREFIX_CHARS = 20
_PREFIX_SCORE = 0.92


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb, autojunk=False).ratio()
    shorter, longer = sorted((na, nb), key=len)
    if len(shorter) >= _MIN_PREFIX_CHARS and longer.startswith(shorter):
        return max(ratio, _PREFIX_SCORE)
    return ratio


def _years_agree(a: int | None, b: int | None) -> bool:
    return a is None or b is None or abs(a - b) <= 1


def _best_title_match(title: str, year: int | None, works: Iterable[openalex.Work]) -> openalex.Work | None:
    best, best_score = None, TITLE_MATCH
    for work in works:
        score = title_similarity(title, work.title)
        if score >= best_score and _years_agree(year, work.year):
            best, best_score = work, score
    return best


def _apply(study_id: int, work: openalex.Work) -> None:
    research_store.apply_work(
        study_id,
        title=work.title,
        authors=work.authors,
        year=work.year,
        venue=work.venue,
        doi=work.doi,
        openalex_id=work.openalex_id,
        oa_url=work.oa_url,
    )


def _settle_identity(study_id: int, *, is_paper: bool) -> int:
    """Merge with any Study sharing a strong id. Returns the surviving id for this Study."""
    row = research_store.study_row(study_id)
    if row is None:
        return study_id
    same = research_store.find_same_study(
        study_id, doi=row["doi"], arxiv_id=row["arxiv_id"], openalex_id=row["openalex_id"]
    )
    if same is None:
        return study_id
    other_id, other_state = same
    if is_paper:
        if other_state == "lead":
            research_store.merge_studies(study_id, other_id)
        return study_id  # two uploads of the same Paper are left for the user
    research_store.merge_studies(other_id, study_id)
    return other_id


def _suggest_match(paper_id: int) -> None:
    row = research_store.study_row(paper_id)
    if row is None or row["possible_match_id"] is not None:
        return
    best_id, best_score = None, TITLE_MATCH - 1e-9
    for lead in research_store.leads_like(paper_id):
        score = title_similarity(row["title"], lead["title"])
        if score > best_score and _years_agree(row["year"], lead["year"]):
            best_id, best_score = int(lead["id"]), score
    if best_id is not None:
        research_store.set_possible_match(paper_id, best_id)


def _resolve_paper_work(paper_id: int) -> openalex.Work | None:
    row = research_store.study_row(paper_id)
    if row is None:
        return None
    for doi in (row["doi"], openalex.arxiv_doi(row["arxiv_id"])):
        if doi:
            work = openalex.work_by_doi(doi)
            if work:
                return work
    if len(row["title"] or "") >= _MIN_TITLE_CHARS:
        return _best_title_match(row["title"], row["year"], openalex.search_title(row["title"]))
    return None


def _resolve_references(paper_id: int, paper_work: openalex.Work | None) -> None:
    refs = [dict(r) for r in research_store.reference_rows(paper_id) if r["state"] == "lead"]
    unresolved = [r for r in refs if not r["openalex_id"]]
    resolved: list[tuple[int, openalex.Work]] = []

    # 1. The Paper's own reference list, matched by title (one cheap batch).
    if paper_work and paper_work.referenced_works and unresolved:
        works = list(openalex.works_by_filter("openalex_id", paper_work.referenced_works, "openalex").values())
        for ref in list(unresolved):
            match = _best_title_match(ref["title"], ref["year"], works)
            if match:
                resolved.append((ref["id"], match))
                works.remove(match)
                unresolved.remove(ref)

    # 2. References that carry a DOI or arXiv id.
    by_doi: dict[str, dict] = {}
    for ref in unresolved:
        doi = openalex.normalize_doi(ref["doi"]) or openalex.arxiv_doi(ref["arxiv_id"])
        if doi:
            by_doi[doi] = ref
    if by_doi:
        found = openalex.works_by_filter("doi", list(by_doi), "doi")
        for doi, work in found.items():
            ref = by_doi.get(doi)
            if ref is not None:
                resolved.append((ref["id"], work))
                unresolved.remove(ref)

    # 3. Crossref title→DOI for the rest (free), then one OpenAlex batch for those DOIs.
    crossref_dois: dict[str, dict] = {}
    for ref in unresolved:
        if len(ref["title"] or "") < _MIN_TITLE_CHARS or ref["doi"]:
            continue
        authors = json.loads(ref["authors_json"] or "[]")
        surname = authors[0].split()[-1] if authors else None
        try:
            candidates = crossref.lookup(ref["title"], surname, ref["year"])
        except crossref.CrossrefError as exc:
            log.warning("Crossref fallback stopped: %s", exc)
            break
        for candidate in candidates:
            if (
                candidate["doi"]
                and title_similarity(ref["title"], str(candidate["title"])) >= TITLE_MATCH
                and _years_agree(ref["year"], candidate["year"])  # type: ignore[arg-type]
            ):
                crossref_dois[str(candidate["doi"])] = ref
                break
    if crossref_dois:
        found = openalex.works_by_filter("doi", list(crossref_dois), "doi")
        for doi, ref in crossref_dois.items():
            work = found.get(doi)
            if work:
                resolved.append((ref["id"], work))
            else:
                research_store.apply_work(
                    ref["id"], title=None, authors=[], year=None, venue=None,
                    doi=doi, openalex_id=None, oa_url=None,
                )

    for lead_id, work in resolved:
        _apply(lead_id, work)
        _settle_identity(lead_id, is_paper=False)


def settle_locally(paper_id: int, *, suggest: bool) -> None:
    """Merge on the identifiers the PDF itself gives (DOI, arXiv id), with no network call:
    an uploaded Lead becomes this Paper, and References naming one work become one Lead.
    With `suggest`, also offer a close-title Lead for the user to confirm."""
    _settle_identity(paper_id, is_paper=True)
    for ref in research_store.reference_rows(paper_id):
        if ref["state"] == "lead" and (ref["doi"] or ref["arxiv_id"]):
            _settle_identity(int(ref["id"]), is_paper=False)
    if suggest:
        _suggest_match(paper_id)


def resolve_paper(paper_id: int) -> None:
    """Resolve one Paper and its References. Raises openalex.BudgetExhausted / ApiError."""
    work = _resolve_paper_work(paper_id)
    if work:
        _apply(paper_id, work)
        _settle_identity(paper_id, is_paper=True)
    _resolve_references(paper_id, work)
    _suggest_match(paper_id)


def api_enabled() -> bool:
    return research_store.get_setting("scholarly_api", "on") == "on"
