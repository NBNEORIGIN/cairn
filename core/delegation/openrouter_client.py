"""Thin httpx wrapper around OpenRouter chat completions.

One-shot calls only. No history, no tool use, no caching, no retry. For
cross-module delegation via ``deek_delegate`` — do NOT reuse this for
Deek's own agent loop (see ``core/models/openai_client.py`` for that).

Per D-B: context (if provided) is sent as its own prior user message,
NOT as a system prompt. OpenRouter passes system prompts through to the
underlying provider where xAI / Anthropic may modify or reject them.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 30.0


class OpenRouterError(Exception):
    """Categorised OpenRouter failure. ``kind`` maps onto delegation outcome enum."""

    def __init__(self, kind: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.kind = kind  # api_error | timeout | refusal
        self.status_code = status_code


def _build_messages(instructions: str, context: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if context:
        messages.append({"role": "user", "content": context})
    messages.append({"role": "user", "content": instructions})
    return messages


def call(
    *,
    model: str,
    instructions: str,
    context: str | None = None,
    max_tokens: int = 4000,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Make a single OpenRouter chat-completions call.

    Returns ``{"response": str, "tokens_in": int, "tokens_out": int,
    "duration_ms": int, "raw": dict}``. Raises ``OpenRouterError`` on
    timeout, transport error, HTTP error, refusal, or malformed payload.
    The caller never sees the API key.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise OpenRouterError(
            "api_error",
            "OPENROUTER_API_KEY is not set in the environment",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Per OpenRouter docs; required for some attribution features.
        "HTTP-Referer": "https://github.com/NBNEORIGIN/deek",
        "X-Title": "Deek deek_delegate",
    }
    payload = {
        "model": model,
        "messages": _build_messages(instructions, context),
        "max_tokens": max_tokens,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise OpenRouterError("timeout", f"OpenRouter timed out after {timeout_seconds}s") from exc
    except httpx.HTTPError as exc:
        raise OpenRouterError("api_error", f"OpenRouter transport error: {exc}") from exc
    duration_ms = int((time.perf_counter() - start) * 1000)

    if resp.status_code >= 400:
        # Body may contain useful error detail; do NOT include request headers.
        body_excerpt = resp.text[:500]
        raise OpenRouterError(
            "api_error",
            f"OpenRouter returned HTTP {resp.status_code}: {body_excerpt}",
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise OpenRouterError("api_error", f"OpenRouter returned non-JSON body: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise OpenRouterError("api_error", "OpenRouter returned no choices")
    message = choices[0].get("message") or {}
    finish_reason = choices[0].get("finish_reason")
    content = message.get("content")

    # Provider-level refusal / safety stop.
    if finish_reason in {"content_filter", "safety"} or (content is None and message.get("refusal")):
        raise OpenRouterError(
            "refusal",
            f"Provider refused the request (finish_reason={finish_reason!r})",
        )
    if content is None:
        raise OpenRouterError("api_error", "OpenRouter response message had no content")

    usage = data.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)

    return {
        "response": content,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "duration_ms": duration_ms,
        "raw": data,
    }
