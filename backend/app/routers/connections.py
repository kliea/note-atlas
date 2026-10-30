"""Spatial connections between notes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import create_connection, delete_connection, get_connection_by_id, list_connections
from app.models import Connection, ConnectionCreate

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=list[Connection])
def get_connections(board_id: int | None = None) -> list[Connection]:
    return list_connections(board_id)


@router.post("", response_model=Connection, status_code=201)
def post_connection(payload: ConnectionCreate) -> Connection:
    try:
        return create_connection(payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="note not found") from None
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "already exists" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.delete("/{connection_id}", status_code=204)
def remove_connection(connection_id: int) -> None:
    if get_connection_by_id(connection_id) is None:
        raise HTTPException(status_code=404, detail="connection not found")
    delete_connection(connection_id)
