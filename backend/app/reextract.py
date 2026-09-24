"""Fold a new extraction run's Claims into a Paper without losing the user's work.

Decision (docs/specs/research-track.md, "Re-extraction"; issues #10, #13):
- Untouched paper Claims are replaced by the new run's.
- Edited or sent-to-board paper Claims are matched, by their original text, to the most
  similar new Claim (local MiniLM). Matched: keep the user's wording (and board link) and
  refresh the original text and quote from the new run. Unmatched: kept, flagged stale
  ("not in the latest extraction") for the user to keep or delete.
- Reader Claims are never touched.
- Deleted paper Claims are tombstones: a new Claim that closely matches one is suppressed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app import research_store
from app.embed import embed_texts
from app.paper_extract import normalize

# MiniLM cosine: paraphrases of one point sit above this; different points of one paper below.
MATCH_THRESHOLD = 0.8

EmbedFn = Callable[[Sequence[str]], list[list[float]]]


@dataclass
class MergePlan:
    matched: dict[int, tuple[str, str | None]] = field(default_factory=dict)  # claim id → new (text, quote)
    stale: list[int] = field(default_factory=list)
    inserts: list[tuple[str, str | None]] = field(default_factory=list)
    suppressed: list[str] = field(default_factory=list)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _similarity(a: str, b: str, va: Sequence[float], vb: Sequence[float]) -> float:
    return 1.0 if normalize(a) == normalize(b) else _cosine(va, vb)


def plan_merge(
    kept: Sequence[tuple[int, str]],
    tombstones: Sequence[str],
    new_items: Sequence[tuple[str, str | None]],
    embed: EmbedFn | None = None,
) -> MergePlan:
    """kept: (claim id, original text) of edited or sent Claims; tombstones: deleted originals."""
    plan = MergePlan()
    new_items = [(text.strip(), quote) for text, quote in new_items if normalize(text)]
    # Drop duplicates within the new run itself.
    seen: set[str] = set()
    unique = []
    for text, quote in new_items:
        if normalize(text) not in seen:
            seen.add(normalize(text))
            unique.append((text, quote))
    if not kept and not tombstones:
        plan.inserts = unique
        return plan

    texts = [t for t, _ in unique] + [t for _, t in kept] + list(tombstones)
    vectors = (embed or embed_texts)(texts) if texts else []
    new_vecs = vectors[: len(unique)]
    kept_vecs = vectors[len(unique) : len(unique) + len(kept)]
    tomb_vecs = vectors[len(unique) + len(kept) :]

    available = []
    for index, (text, quote) in enumerate(unique):
        if any(
            _similarity(text, tomb, new_vecs[index], tomb_vecs[j]) >= MATCH_THRESHOLD
            for j, tomb in enumerate(tombstones)
        ):
            plan.suppressed.append(text)
        else:
            available.append(index)

    # One-to-one, most similar pairs first.
    pairs = sorted(
        (
            (_similarity(unique[n][0], kept[k][1], new_vecs[n], kept_vecs[k]), k, n)
            for k in range(len(kept))
            for n in available
        ),
        reverse=True,
    )
    used_kept: set[int] = set()
    used_new: set[int] = set()
    for score, k, n in pairs:
        if score < MATCH_THRESHOLD:
            break
        if k in used_kept or n in used_new:
            continue
        used_kept.add(k)
        used_new.add(n)
        plan.matched[kept[k][0]] = unique[n]
    plan.stale = [claim_id for k, (claim_id, _) in enumerate(kept) if k not in used_kept]
    plan.inserts = [unique[n] for n in available if n not in used_new]
    return plan


def merge_claims(
    study_id: int, kind: str, new_items: Sequence[tuple[str, str | None]], embed: EmbedFn | None = None
) -> MergePlan:
    """Apply a new run's Claims of one kind to a Paper (first extraction or re-extraction)."""
    kept, tombstones = research_store.claims_for_merge(study_id, kind)
    plan = plan_merge(kept, tombstones, new_items, embed)
    research_store.apply_claim_merge(study_id, kind, plan.matched, plan.stale, plan.inserts)
    return plan
