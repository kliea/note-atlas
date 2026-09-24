"""Single local-LLM client.

All model access goes through this module so later phases can swap Ollama
for llama.cpp without touching routers.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from pydantic import BaseModel

from app.config import ollama_host, ollama_model

_PING_TIMEOUT_SECONDS = 3.0
_GENERATE_TIMEOUT_SECONDS = 180.0
# Context windows come in a few sizes so Ollama doesn't reload the model for every prompt.
_CONTEXT_BUCKETS = (4096, 8192, 16384, 32768)
_REPLY_RESERVE_TOKENS = 1024
_CHARS_PER_TOKEN = 3  # conservative, so the estimate errs toward a larger window

Priority = Literal["board", "research"]


class LlmError(Exception):
    """Ollama was unreachable or returned an unusable response."""


class LlmPingResult(BaseModel):
    reachable: bool
    model: str
    host: str
    model_present: bool
    error: str | None = None


def ping() -> LlmPingResult:
    """Ask Ollama whether it is up and whether the configured model exists."""
    host = ollama_host()
    model = ollama_model()
    url = f"{host}/api/tags"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_PING_TIMEOUT_SECONDS) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return LlmPingResult(
            reachable=False,
            model=model,
            host=host,
            model_present=False,
            error=f"HTTP {exc.code}",
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return LlmPingResult(
            reachable=False,
            model=model,
            host=host,
            model_present=False,
            error=str(reason),
        )
    except TimeoutError:
        return LlmPingResult(
            reachable=False,
            model=model,
            host=host,
            model_present=False,
            error="timeout",
        )

    names = [str(item.get("name", "")) for item in payload.get("models", [])]
    model_present = _model_in_tags(model, names)
    return LlmPingResult(
        reachable=True,
        model=model,
        host=host,
        model_present=model_present,
        error=None,
    )


def _http_error(model: str, code: int) -> str:
    if code == 404:
        return f"Ollama model {model} not found (HTTP 404)"
    return f"HTTP {code}"


def _model_in_tags(model: str, names: list[str]) -> bool:
    """Ollama may list `name` or `name:latest`; accept either form."""
    variants = {model, f"{model}:latest"}
    if ":" in model:
        variants.add(model.rsplit(":", 1)[0])
    return any(name in variants or name.startswith(f"{model}") for name in names)


def context_size(messages: list[dict[str, str]]) -> int:
    """Smallest bucketed context window that fits the prompt plus a reply."""
    chars = sum(len(m.get("content", "")) for m in messages)
    needed = chars // _CHARS_PER_TOKEN + _REPLY_RESERVE_TOKENS
    for bucket in _CONTEXT_BUCKETS:
        if needed <= bucket:
            return bucket
    raise LlmError(f"prompt too long for the model context (~{needed} tokens)")


# Board work (polish, Ask) is interactive, so research calls wait until none is in flight.
# A research call already running is never interrupted.
_board_idle = threading.Condition()
_board_in_flight = 0


@contextmanager
def _priority_slot(priority: Priority) -> Iterator[None]:
    global _board_in_flight
    if priority == "research":
        with _board_idle:
            _board_idle.wait_for(lambda: _board_in_flight == 0)
        yield
        return
    with _board_idle:
        _board_in_flight += 1
    try:
        yield
    finally:
        with _board_idle:
            _board_in_flight -= 1
            _board_idle.notify_all()


def _base_payload(messages: list[dict[str, str]], *, stream: bool, temperature: float | None) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": context_size(messages)}
    if temperature is not None:
        options["temperature"] = temperature
    return {
        "model": ollama_model(),
        "messages": messages,
        "stream": stream,
        # qwen3 (and similar) otherwise spend minutes in a hidden reasoning trace
        "think": False,
        "options": options,
        # Ollama silently drops the start of a prompt that overflows the context;
        # these make it fail loudly instead (HTTP 400).
        "truncate": False,
        "shift": False,
    }


def chat(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    schema: dict[str, Any] | None = None,
    temperature: float | None = None,
    priority: Priority = "board",
    timeout: float = _GENERATE_TIMEOUT_SECONDS,
) -> str:
    """Send a chat completion to Ollama. All generation goes through here."""
    host = ollama_host()
    model = ollama_model()
    payload = _base_payload(messages, stream=False, temperature=temperature)
    if schema is not None:
        # Constrains output to this JSON schema.
        payload["format"] = schema
    elif json_mode:
        # Forces a JSON object; the model still has to match our schema.
        payload["format"] = "json"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with _priority_slot(priority), urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LlmError(_http_error(model, exc.code)) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise LlmError(str(reason)) from exc
    except TimeoutError as exc:
        raise LlmError("timeout") from exc

    content = raw.get("message", {}).get("content", "")
    if isinstance(content, dict):
        return json.dumps(content)
    if not isinstance(content, str) or not content.strip():
        raise LlmError("empty model response")
    return content


def chat_stream(
    messages: list[dict[str, str]],
    *,
    timeout: float = _GENERATE_TIMEOUT_SECONDS,
) -> Iterator[str]:
    """Yield assistant text pieces as Ollama streams them."""
    host = ollama_host()
    model = ollama_model()
    payload = _base_payload(messages, stream=True, temperature=None)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    hide_think = "qwen3" in model.lower()
    held = ""
    released = not hide_think
    try:
        with _priority_slot("board"), urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done") is True:
                    if not released and held:
                        yield held
                    return
                piece = data.get("message", {}).get("content", "")
                if not isinstance(piece, str) or not piece:
                    continue
                if released:
                    yield piece
                    continue
                held += piece
                close = held.find("</think>")
                if close >= 0:
                    released = True
                    rest = held[close + len("</think>") :].lstrip()
                    held = ""
                    if rest:
                        yield rest
    except urllib.error.HTTPError as exc:
        raise LlmError(_http_error(model, exc.code)) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise LlmError(str(reason)) from exc
    except TimeoutError as exc:
        raise LlmError("timeout") from exc
