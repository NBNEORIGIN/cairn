"""
Shared embedding utility for the wiki layer.

Tries in order:
  1. Ollama nomic-embed-text (local, free)
  2. OpenAI text-embedding-3-small (~£0.01/1M tokens, 768-dim)
  3. DeepSeek embedding API

Returns 768-dim vectors to match the existing pgvector schema.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

# Module-level cache so we don't re-test providers on every call
_cached_embed_fn: Callable | None = None
_cache_checked = False


def get_embed_fn() -> Callable[[str], list[float]] | None:
    """Get an embedding function. Cached after first successful probe."""
    global _cached_embed_fn, _cache_checked

    if _cache_checked:
        return _cached_embed_fn

    _cache_checked = True
    _cached_embed_fn = _probe_providers()
    return _cached_embed_fn


def reset_cache() -> None:
    """Reset the cached provider (useful after env var changes)."""
    global _cached_embed_fn, _cache_checked
    _cached_embed_fn = None
    _cache_checked = False


def _probe_providers() -> Callable[[str], list[float]] | None:
    """Try each provider in order, return the first that works."""

    # 1. Ollama (local, free)
    try:
        from core.models.ollama_client import OllamaClient
        client = OllamaClient(
            base_url=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
            model='nomic-embed-text',
        )
        test = client.embed("test")
        if test and len(test) > 0:
            logger.info("Wiki embedding: using Ollama nomic-embed-text")
            return client.embed
    except Exception:
        pass

    # 2. OpenAI text-embedding-3-small (768-dim)
    openai_key = os.getenv('OPENAI_API_KEY', '')
    if openai_key:
        try:
            import httpx

            def openai_embed(text: str) -> list[float]:
                resp = httpx.post(
                    'https://api.openai.com/v1/embeddings',
                    headers={
                        'Authorization': f'Bearer {openai_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': 'text-embedding-3-small',
                        'input': text[:8000],
                        'dimensions': 768,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                return resp.json()['data'][0]['embedding']

            test = openai_embed("test")
            if test and len(test) == 768:
                logger.info("Wiki embedding: using OpenAI text-embedding-3-small (768-dim)")
                return openai_embed
        except Exception as exc:
            logger.debug("OpenAI embedding unavailable: %s", exc)

    # 3. DeepSeek
    deepseek_key = os.getenv('DEEPSEEK_API_KEY', '')
    if deepseek_key:
        try:
            import httpx

            def deepseek_embed(text: str) -> list[float]:
                resp = httpx.post(
                    'https://api.deepseek.com/embeddings',
                    headers={
                        'Authorization': f'Bearer {deepseek_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': 'deepseek-chat',
                        'input': text[:8000],
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()['data'][0]['embedding']
                if len(data) < 768:
                    data.extend([0.0] * (768 - len(data)))
                return data[:768]

            test = deepseek_embed("test")
            if test and len(test) == 768:
                logger.info("Wiki embedding: using DeepSeek embedding (768-dim)")
                return deepseek_embed
        except Exception as exc:
            logger.debug("DeepSeek embedding unavailable: %s", exc)

    logger.warning("No embedding provider available for wiki layer")
    return None
