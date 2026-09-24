"""Choose a Paper's Parent Papers: the References it substantially builds on.

Decision (docs/specs/research-track.md, "Leads"; issue #9):
- Shortlist References by where they're cited (Method > Results > Intro/Related work),
  boosted by Semantic Scholar's influence flags when the user has a key.
- The local model reads the Paper's Method section and the shortlist's citation sentences,
  PICKS the References the Paper builds on, and scores each (0-10) with a one-line reason.
  (Asking it to score every Reference instead makes a small model's scores collapse.)
- When the Paper's citations aren't linked to its References (common in some styles),
  the model instead reads the reference list against the Method section.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.llm import LlmError, chat
from app.paper_extract import normalize

SHORTLIST_SIZE = 15
PARENT_THRESHOLD = 0.6  # builds_on >= 6 of 10
MAX_PARENTS = 5
_MAX_UNLINKED_REFS = 80
_METHOD_CHARS = 12_000
_S2_INFLUENTIAL_BOOST = 3.0
# Small models mislabel item numbers, so each judgement repeats the title and is matched on it.
_TITLE_AGREEMENT = 0.6

_METHOD = re.compile(
    r"method|approach|model|framework|architecture|system|design|experiment|setup|"
    r"implementation|dataset|data|pipeline|procedure|materials",
    re.IGNORECASE,
)
_RESULTS = re.compile(r"result|evaluation|discussion|analysis|finding|benchmark", re.IGNORECASE)
_BACKGROUND = re.compile(r"introduction|related|background|prior|literature|motivation", re.IGNORECASE)

_JUDGEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "judgements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "title": {"type": "string"},
                    "builds_on": {"type": "integer", "minimum": 0, "maximum": 10},
                    "reason": {"type": "string"},
                },
                "required": ["number", "title", "builds_on", "reason"],
            },
        }
    },
    "required": ["judgements"],
}

# No example reasons: a small model copies the first example onto every item.
_SCALE = (
    "title: the reference's title, copied from the list.\n"
    "builds_on: 0-10. 9-10: this paper is a direct extension or new version of it, or cannot work "
    "without it. 7-8: it adopts or evaluates the reference's method, model, dataset, or tool as a core "
    "part of its work. 5-6: it uses the reference substantially but not centrally, e.g. as a comparison "
    "baseline. 0-4: background.\n"
    "reason: under 10 words saying concretely what this paper takes from the reference and how "
    "(name the thing: which dataset, which method), in your own words."
)

_PICK = (
    "Pick the references this paper BUILDS ON (at most 8): ones whose method, model, dataset, tool, "
    "or theory this paper extends, adapts, evaluates, or directly relies on. Skip references cited only "
    "as background or motivation."
)


@dataclass
class Candidate:
    study_id: int
    title: str
    year: int | None
    mention_count: int
    contexts: list[dict[str, str]] = field(default_factory=list)
    influential: bool = False
    intents: list[str] = field(default_factory=list)

    @property
    def heuristic(self) -> float:
        score = sum(section_weight(c.get("section", "")) for c in self.contexts)
        # Mentions beyond the stored contexts still count, at a background rate.
        score += max(0, self.mention_count - len(self.contexts)) * 1.0
        if self.influential:
            score += _S2_INFLUENTIAL_BOOST
        return score


@dataclass
class ParentJudgement:
    score: float  # 0-1
    reason: str


def section_weight(head: str) -> float:
    if _METHOD.search(head):
        return 3.0
    if _RESULTS.search(head):
        return 2.0
    if _BACKGROUND.search(head):
        return 1.0
    return 1.5


def citations_linked(candidates: list[Candidate]) -> bool:
    """Enough References are linked to in-text citations for the contexts to be a real signal."""
    if not candidates:
        return False
    cited = sum(1 for c in candidates if c.mention_count > 0)
    return cited >= max(3, int(0.3 * len(candidates)))


def shortlist(candidates: list[Candidate], size: int = SHORTLIST_SIZE) -> list[Candidate]:
    cited = [c for c in candidates if c.mention_count > 0 or c.influential]
    return sorted(cited, key=lambda c: (-c.heuristic, -c.mention_count, c.study_id))[:size]


def _ask(prompt: str) -> list[dict[str, Any]]:
    raw = chat(
        [{"role": "user", "content": prompt}],
        schema=_JUDGEMENT_SCHEMA,
        temperature=0,
        priority="research",
        timeout=900.0,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LlmError("model returned invalid JSON") from exc
    return list(data.get("judgements", [])) if isinstance(data, dict) else []


def _similar(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    return SequenceMatcher(None, na, nb, autojunk=False).ratio() if na and nb else 0.0


def _which(numbered: list[Candidate], item: dict[str, Any]) -> Candidate | None:
    """The reference a judgement is about: by its echoed title, else by its number."""
    title = str(item.get("title") or "")
    if title:
        best = max(numbered, key=lambda c: _similar(title, c.title))
        if _similar(title, best.title) >= _TITLE_AGREEMENT:
            return best
        return None  # the title names nothing in the list: don't trust the number either
    try:
        index = int(item.get("number"))
    except (TypeError, ValueError):
        return None
    return numbered[index] if 0 <= index < len(numbered) else None


def _collect(numbered: list[Candidate], judgements: list[dict[str, Any]]) -> dict[int, ParentJudgement]:
    out: dict[int, ParentJudgement] = {}
    for item in judgements:
        try:
            score = max(0, min(10, int(item.get("builds_on"))))
        except (TypeError, ValueError):
            continue
        candidate = _which(numbered, item) if numbered else None
        if candidate is None or candidate.study_id in out:
            continue
        reason = " ".join(str(item.get("reason", "")).split())[:160]
        out[candidate.study_id] = ParentJudgement(score=score / 10, reason=reason)
    return out


def _describe(candidate: Candidate) -> str:
    year = f" ({candidate.year})" if candidate.year else ""
    lines = [f"{candidate.title}{year} — cited {candidate.mention_count}x"]
    if candidate.intents:
        lines.append(f"   Semantic Scholar intents: {', '.join(candidate.intents)}")
    for context in candidate.contexts:
        lines.append(f"   [{context.get('section') or 'body'}] {context.get('sentence', '')}")
    return "\n".join(lines)


def judge_linked(
    title: str, abstract: str, method_text: str, candidates: list[Candidate]
) -> dict[int, ParentJudgement]:
    """Citations are linked: show the Method and each shortlisted Reference's citing sentences."""
    if not candidates:
        return {}
    listing = "\n".join(f"{i}. {_describe(c)}" for i, c in enumerate(candidates))
    prompt = (
        "You are reading an academic paper: its method, and the references it cites with the sentences "
        f"where it cites them. {_PICK}\n{_SCALE}\n"
        "Return judgements only for the references you pick: number, title, builds_on, reason.\n\n"
        f"PAPER: {title}\nABSTRACT: {abstract}\n\nMETHOD:\n{method_text[:_METHOD_CHARS]}\n\n"
        f"REFERENCES:\n{listing}"
    )
    return _collect(candidates, _ask(prompt))


def judge_unlinked(
    title: str, abstract: str, method_text: str, candidates: list[Candidate]
) -> dict[int, ParentJudgement]:
    """Citations weren't linked in the text: judge the reference list against the Method section."""
    numbered = candidates[:_MAX_UNLINKED_REFS]
    if not numbered:
        return {}
    listing = "\n".join(
        f"{i}. {c.title[:150]}{f' ({c.year})' if c.year else ''}" for i, c in enumerate(numbered)
    )
    prompt = (
        f"You are reading an academic paper's method and its reference list. {_PICK}\n"
        f"{_SCALE}\nReturn judgements only for the references you pick: number, title, builds_on, reason.\n\n"
        f"PAPER: {title}\nABSTRACT: {abstract}\n\nMETHOD:\n{method_text[:_METHOD_CHARS]}\n\n"
        f"REFERENCES:\n{listing}"
    )
    return _collect(numbered, _ask(prompt))


def method_text(sections: list[tuple[str, str]], body: str) -> str:
    """The Method-like sections, or the start of the body when headings don't say."""
    chosen = [f"## {head}\n{text}" for head, text in sections if _METHOD.search(head or "")]
    return "\n\n".join(chosen) if chosen else body[:_METHOD_CHARS]


def choose_parents(
    title: str,
    abstract: str,
    candidates: list[Candidate],
    sections: list[tuple[str, str]],
    body: str,
) -> dict[int, ParentJudgement]:
    method = method_text(sections, body)
    if citations_linked(candidates):
        return judge_linked(title, abstract, method, shortlist(candidates))
    return judge_unlinked(title, abstract, method, candidates)
