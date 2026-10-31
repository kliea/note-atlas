"""Vector search and reindex."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.index import reindex_all, search
from app.models import SearchHit

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchHit])
def get_search(
    q: str = Query(min_length=1),
    k: int = Query(default=5, ge=1, le=20),
    board_id: int | None = Query(default=None),
) -> list[SearchHit]:
    return search(q.strip(), k, board_id=board_id)


@router.post("/reindex")
def post_reindex() -> dict[str, int]:
    try:
        return reindex_all()
    except Exception as exc:  # noqa: BLE001 — surface embed/vec errors as 502
        raise HTTPException(status_code=502, detail=str(exc)) from exc
