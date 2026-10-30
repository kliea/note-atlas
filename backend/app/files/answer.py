"""Grounded answers for the Files pipeline (lab Part 6: `generate_answer`).

The lab's prompt, kept as written: one user message, ONLY the retrieved context, and an exact
refusal line when the answer isn't there. The model is FILES_LLM_MODEL (phi3), never OLLAMA_MODEL,
unless a question names another pulled model (enhancement 6).

With FILES_MEMORY_TURNS > 0 (enhancement 5), earlier questions and answers from the same scope
are added in their own section, so a follow-up like "what about its limitations?" can be
understood; the prompt still says facts come ONLY from the context.
"""

from __future__ import annotations

from collections.abc import Iterator

from app import llm
from app.files.config import show_sources
from app.files.models import RetrievedChunk

REFUSAL = "The information is not available in the uploaded documents."

_PROMPT = """You are a helpful assistant.

Use ONLY the context below.
{memory}
Context:
{context}

Question:
{question}

If the answer is not found, say:
"{refusal}"

Answer:
"""

_MEMORY = """
Earlier in this conversation (use it only to understand what the question refers to; every fact
in your answer must come from the Context, not from these earlier answers):
{turns}
"""

Turn = tuple[str, str]  # (question, answer)


def build_prompt(question: str, chunks: list[RetrievedChunk], memory: list[Turn] | None = None) -> str:
    context = "\n\n".join(chunk.text for chunk in chunks)
    memory_block = ""
    if memory:
        turns = "\n".join(f"Q: {q}\nA: {a}" for q, a in memory)
        memory_block = _MEMORY.format(turns=turns)
    return _PROMPT.format(memory=memory_block, context=context, question=question, refusal=REFUSAL)


def messages_for(question: str, chunks: list[RetrievedChunk], memory: list[Turn] | None = None) -> list[dict[str, str]]:
    return [{"role": "user", "content": build_prompt(question, chunks, memory)}]


def stream_answer(
    question: str, chunks: list[RetrievedChunk], *, model: str, memory: list[Turn] | None = None
) -> Iterator[str]:
    yield from llm.chat_stream(messages_for(question, chunks, memory), model=model)


def is_refusal(text: str) -> bool:
    return text.strip().strip('"').strip() == REFUSAL


def source_line(text: str, chunks: list[RetrievedChunk]) -> list[str] | None:
    """Distinct `filename · p.N` sources in retrieval order (enhancement 3).

    None when the source line is turned off, nothing was retrieved, or the answer is the refusal
    (the chunks didn't support an answer, so they aren't its sources).
    """
    if not show_sources() or not chunks or is_refusal(text):
        return None
    return list(dict.fromkeys(f"{chunk.filename} · p.{chunk.page_start}" for chunk in chunks))
