"""Additive context on extracted points."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import get_point, patch_point
from app.models import Point, PointPatch

router = APIRouter(prefix="/points", tags=["points"])


@router.patch("/{point_id}", response_model=Point)
def patch_point_by_id(point_id: int, payload: PointPatch) -> Point:
    if get_point(point_id) is None:
        raise HTTPException(status_code=404, detail="point not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="no changes")
    updated = patch_point(point_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="point not found")
    return updated
