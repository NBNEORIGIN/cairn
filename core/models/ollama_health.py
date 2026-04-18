"""
Ollama reachability circuit breaker.

When Deek is hybrid-deployed (Hetzner API → GPU server Ollama over tunnel),
the Ollama endpoint may be temporarily unreachable. Every router decision
must not block on a network call. This module caches reachability state
with a short TTL so routing stays fast and degrades gracefully.

State transitions:
- unknown → probe → healthy or unreachable
- healthy: use local (Ollama routing enabled), re-probe every HEALTHY_TTL
- unreachable: fall back to API, re-probe every UNREACHABLE_TTL

The TTLs are asymmetric: when healthy we trust the cache for a minute;
when unreachable we retry more often so we recover quickly when the
tunnel comes back up.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

HEALTHY_TTL_SEC = 60        # re-probe once a minute when healthy
UNREACHABLE_TTL_SEC = 15    # re-probe every 15s when down (faster recovery)
PROBE_TIMEOUT_SEC = 3.0     # cap per-probe latency


@dataclass
class HealthState:
    reachable: bool = False
    last_probe_at: float = 0.0
    last_latency_ms: Optional[int] = None
    last_error: Optional[str] = None
    base_url: str = ''


_state = HealthState()


def _base_url() -> str:
    return os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')


def is_reachable() -> bool:
    """Return cached reachability, probing on TTL expiry.

    Non-blocking for callers: the first call after TTL expiry probes
    synchronously (bounded by PROBE_TIMEOUT_SEC), subsequent calls use
    the cached value.
    """
    now = time.monotonic()
    ttl = HEALTHY_TTL_SEC if _state.reachable else UNREACHABLE_TTL_SEC

    if _state.last_probe_at and (now - _state.last_probe_at) < ttl:
        return _state.reachable

    return _probe()


def _probe() -> bool:
    """Synchronously probe Ollama /api/tags endpoint. Updates module state."""
    url = _base_url()
    _state.base_url = url
    start = time.monotonic()
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT_SEC) as client:
            r = client.get(f'{url}/api/tags')
            if r.status_code == 200:
                _state.reachable = True
                _state.last_error = None
                _state.last_latency_ms = int((time.monotonic() - start) * 1000)
                _state.last_probe_at = time.monotonic()
                return True
            _state.last_error = f'HTTP {r.status_code}'
    except httpx.TimeoutException:
        _state.last_error = f'timeout after {PROBE_TIMEOUT_SEC}s'
    except httpx.ConnectError as e:
        _state.last_error = f'connect error: {e}'
    except Exception as e:
        _state.last_error = f'{type(e).__name__}: {e}'

    # Probe failed
    _state.reachable = False
    _state.last_latency_ms = None
    _state.last_probe_at = time.monotonic()
    logger.warning('[ollama_health] unreachable at %s: %s', url, _state.last_error)
    return False


def force_recheck() -> bool:
    """Reset the probe cache and re-check immediately. For admin/debug."""
    _state.last_probe_at = 0.0
    return is_reachable()


def snapshot() -> dict:
    """Return current state for /health endpoint reporting."""
    # Mask the full URL to just host (avoid leaking tailnet addresses to public health)
    host = _state.base_url
    if '://' in host:
        host = host.split('://', 1)[1]
    if '/' in host:
        host = host.split('/', 1)[0]
    return {
        'reachable': _state.reachable,
        'last_probe_at': _state.last_probe_at,
        'last_latency_ms': _state.last_latency_ms,
        'last_error': _state.last_error,
        'host': host or 'unset',
    }


# ── Hardware profile routing ────────────────────────────────────────────────

# Context window limits per hardware profile — governs whether the router
# will attempt local routing given the estimated context size.
# cloud_cpu  — no GPU, never route local (current Hetzner without GPU backend)
# dev_desktop — RTX 3050 8GB, Qwen 7B fits up to ~6k context
# single_3090 — RTX 3090 24GB, Qwen 32B fits up to ~8k context
# dual_3090   — two RTX 3090s, Qwen 72B fits up to ~16k context
HARDWARE_PROFILES = {
    'cloud_cpu': 0,
    'dev_desktop': 6000,
    'single_3090': 8000,
    'dual_3090': 16000,
}


def local_context_limit() -> int:
    """Return the context token limit below which local routing is viable
    for the current DEEK_HARDWARE_PROFILE. Returns 0 for cloud_cpu which
    disables local routing entirely.
    """
    profile = (os.getenv('DEEK_HARDWARE_PROFILE') or 'dev_desktop').strip()
    return HARDWARE_PROFILES.get(profile, 6000)
