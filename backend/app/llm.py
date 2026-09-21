"""Single local-LLM client.

All model access goes through this module so later phases can swap Ollama
for llama.cpp without touching routers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from app.config import ollama_host, ollama_model

_PING_TIMEOUT_SECONDS = 3.0
_GENERATE_TIMEOUT_SECONDS = 180.0


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


def chat(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    timeout: float = _GENERATE_TIMEOUT_SECONDS,
) -> str:
    """Send a chat completion to Ollama. All generation goes through here."""
    host = ollama_host()
    model = ollama_model()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        # qwen3 (and similar) otherwise spend minutes in a hidden reasoning trace
        "think": False,
    }
    if json_mode:
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
    }
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
