"""Grounded answers for the Files pipeline (lab Part 6: `generate_answer`).

The lab's prompt, kept as written: one user message, ONLY the retrieved context, and an exact
refusal line when the answer isn't there. The model is FILES_LLM_MODEL (phi3), never OLLAMA_MODEL.
"""

from __future__ import annotations

from collections.abc import Iterator

from app import llm
from app.files.config import llm_model
from app.files.models import RetrievedChunk

REFUSAL = "The information is not available in the uploaded documents."

_PROMPT = """You are a helpful assistant.

Use ONLY the context below.

Context:
{context}

Question:
{question}

If the answer is not found, say:
"{refusal}"

Answer:
"""


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    context = "\n\n".join(chunk.text for chunk in chunks)
    return _PROMPT.format(context=context, question=question, refusal=REFUSAL)


def messages_for(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    return [{"role": "user", "content": build_prompt(question, chunks)}]


def stream_answer(question: str, chunks: list[RetrievedChunk]) -> Iterator[str]:
    yield from llm.chat_stream(messages_for(question, chunks), model=llm_model())


def generate_answer(question: str, chunks: list[RetrievedChunk]) -> str:
    return "".join(stream_answer(question, chunks)).strip()
