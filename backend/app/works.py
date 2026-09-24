"""The canonical-work record and errors shared by every scholarly source (OpenAlex, Semantic Scholar).

`Work.id` is the source's own id (an OpenAlex `W…` id or a Semantic Scholar paperId), and
`referenced_works` holds ids from the same source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Work:
    id: str
    doi: str | None
    title: str
    year: int | None
    authors: list[str]
    venue: str | None
    oa_url: str | None
    referenced_works: list[str] = field(default_factory=list)
    fwci: float | None = None
    abstract: str | None = None
    arxiv_id: str | None = None
    cited_by_count: int | None = None


class ApiError(RuntimeError):
    """A scholarly source failed for a reason other than its budget or rate limit."""


class BudgetExhausted(RuntimeError):
    """The source won't answer until `reset_at` (daily budget spent, or rate-limited)."""

    def __init__(self, reset_at: datetime, source: str = "OpenAlex") -> None:
        super().__init__(f"{source} is unavailable until {reset_at.isoformat()}")
        self.reset_at = reset_at
