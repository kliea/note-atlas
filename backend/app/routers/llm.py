"""LLM connectivity probes."""

from __future__ import annotations

from fastapi import APIRouter

from app.llm import LlmPingResult, ping

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/ping", response_model=LlmPingResult)
def llm_ping() -> LlmPingResult:
    return ping()
