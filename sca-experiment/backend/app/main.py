"""Minimal FastAPI fixture for the SCA experiment. Dependencies are the point."""

from __future__ import annotations

from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="SCA Experiment", version="0.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5253", "http://127.0.0.1:5253"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str
    embed_model: str


class NoteIn(BaseModel):
    title: str
    body: Optional[str] = None


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", embed_model="all-MiniLM-L6-v2")


@app.post("/notes")
def create_note(note: NoteIn) -> dict:
    return {"id": 1, "title": note.title, "body": note.body or ""}


@app.get("/llm/ping")
def llm_ping() -> dict:
    # Touches the planted HTTP client. Local-only; no exploit payload.
    try:
        httpx.get("http://127.0.0.1:9", timeout=0.2)
    except httpx.HTTPError:
        pass
    return {"reachable": False, "model": "fixture"}
