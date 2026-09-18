"""FastAPI entrypoint for Note Atlas."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_env
from app.db import init_db
from app.routers import ask, connections, health, llm, notes, points, search

load_env()

# Vite's default origin. Keep this tight; later phases can widen if needed.
_VITE_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Note Atlas", version="0.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_VITE_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.include_router(health.router)
app.include_router(llm.router)
app.include_router(notes.router)
app.include_router(points.router)
app.include_router(connections.router)
app.include_router(search.router)
app.include_router(ask.router)
