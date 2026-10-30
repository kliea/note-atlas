"""Boards: one domain of knowledge each (ADR 0002)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import (
    board_folder_ids,
    create_board,
    delete_board_row,
    get_board,
    list_boards,
    open_board,
    patch_board,
)
from app.files import service as files_service
from app.files.service import BuildInProgress
from app.models import Board, BoardCreate, BoardPatch

router = APIRouter(prefix="/boards", tags=["boards"])


@router.get("", response_model=list[Board])
def get_boards() -> list[Board]:
    return list_boards()


@router.post("", response_model=Board, status_code=201)
def post_board(payload: BoardCreate) -> Board:
    try:
        return create_board(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/{board_id}", response_model=Board)
def patch_board_by_id(board_id: int, payload: BoardPatch) -> Board:
    try:
        board = patch_board(board_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if board is None:
        raise HTTPException(status_code=404, detail="board not found")
    return board


@router.post("/{board_id}/open", response_model=Board)
def post_open_board(board_id: int) -> Board:
    board = open_board(board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="board not found")
    return board


@router.delete("/{board_id}", status_code=204)
def delete_board_by_id(board_id: int) -> None:
    """Deletes the Board's notes, Strings, and Files folders. Referenced Papers stay."""
    if get_board(board_id) is None:
        raise HTTPException(status_code=404, detail="board not found")
    if len(list_boards()) <= 1:
        raise HTTPException(status_code=409, detail="You can't delete your last Board.")
    try:
        for folder_id in board_folder_ids(board_id):
            files_service.delete_folder(folder_id)
        delete_board_row(board_id)
    except BuildInProgress:
        raise HTTPException(
            status_code=409, detail="A Files folder on this Board is still indexing. Try again shortly."
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
