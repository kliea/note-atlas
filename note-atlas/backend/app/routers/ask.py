"""Streaming RAG answers."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.llm import LlmError
from app.models import AskRequest
from app.rag import plan_ask, stream_answer

router = APIRouter(tags=["ask"])


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/ask")
def post_ask(body: AskRequest) -> StreamingResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    def events() -> Iterator[str]:
        try:
            plan = plan_ask(question, k=body.k, note_ids=body.note_ids)
            yield _sse(
                "meta",
                {
                    "grounded": plan.grounded,
                    "citations": [item.model_dump() for item in plan.citations],
                },
            )
            for token in stream_answer(plan):
                yield _sse("token", {"text": token})
            yield _sse("done", {})
        except LlmError as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
