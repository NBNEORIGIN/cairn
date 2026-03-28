"""
Cache statistics tracker — records prompt caching hits per provider.

SQLite-backed (uses existing MemoryStore connection pattern).
Called after each API response to track cache hit rates and cost savings.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Cache read costs per token (10% of input price)
_CACHE_COST_PER_TOKEN: dict[str, float] = {
    'sonnet':   0.0000003,    # $0.30/MTok cached
    'claude':   0.0000003,    # alias
    'opus':     0.0000005,    # $0.50/MTok cached
    'gpt54':    0.00000025,   # $0.25/MTok cached
    'openai':   0.00000025,   # alias
    'deepseek': 0.000000027,  # $0.027/MTok cached
    'ollama':   0.0,
    'local':    0.0,
}

# Full input costs per token (what you'd pay without caching)
_INPUT_COST_PER_TOKEN: dict[str, float] = {
    'sonnet':   0.000003,     # $3.00/MTok
    'claude':   0.000003,
    'opus':     0.000015,     # $15.00/MTok
    'gpt54':    0.0000025,    # $2.50/MTok
    'openai':   0.0000025,
    'deepseek': 0.00000027,   # $0.27/MTok
    'ollama':   0.0,
    'local':    0.0,
}


class CacheManager:
    """Track prompt caching statistics per provider in SQLite."""

    def __init__(self, store):
        self._conn = store.conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS cache_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                date TEXT NOT NULL,
                requests INTEGER NOT NULL DEFAULT 0,
                cached_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_saved_usd REAL NOT NULL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_cache_stats_provider_date
                ON cache_stats(provider, date);
        """)
        self._conn.commit()

    def record_request(
        self,
        provider: str,
        input_tokens: int,
        cached_tokens: int,
    ) -> None:
        """Called after each API response with usage data."""
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        saved = self._cost_saved(provider, cached_tokens)

        # Upsert: increment today's row for this provider
        existing = self._conn.execute(
            'SELECT id, requests, cached_tokens, total_tokens, cost_saved_usd '
            'FROM cache_stats WHERE provider = ? AND date = ?',
            (provider, today),
        ).fetchone()

        if existing:
            self._conn.execute(
                'UPDATE cache_stats SET '
                'requests = requests + 1, '
                'cached_tokens = cached_tokens + ?, '
                'total_tokens = total_tokens + ?, '
                'cost_saved_usd = cost_saved_usd + ? '
                'WHERE id = ?',
                (cached_tokens, input_tokens, saved, existing[0]),
            )
        else:
            self._conn.execute(
                'INSERT INTO cache_stats '
                '(provider, date, requests, cached_tokens, total_tokens, cost_saved_usd) '
                'VALUES (?, ?, 1, ?, ?, ?)',
                (provider, today, cached_tokens, input_tokens, saved),
            )
        self._conn.commit()

    def get_stats(self, provider: str, days: int = 7) -> dict:
        """
        Returns aggregated cache stats for the last N days.

        {
            'hit_rate': 0.73,
            'tokens_saved': 142000,
            'cost_saved_usd': 0.71,
            'requests': 94,
        }
        """
        rows = self._conn.execute(
            'SELECT SUM(requests), SUM(cached_tokens), '
            'SUM(total_tokens), SUM(cost_saved_usd) '
            'FROM cache_stats '
            'WHERE provider = ? '
            'AND date >= date("now", ?)',
            (provider, f'-{days} days'),
        ).fetchone()

        if not rows or not rows[0]:
            return {
                'hit_rate': 0.0,
                'tokens_saved': 0,
                'cost_saved_usd': 0.0,
                'requests': 0,
            }

        total_requests = int(rows[0])
        total_cached = int(rows[1] or 0)
        total_input = int(rows[2] or 0)
        total_saved = float(rows[3] or 0.0)

        hit_rate = total_cached / max(total_input, 1)

        return {
            'hit_rate': round(hit_rate, 4),
            'tokens_saved': total_cached,
            'cost_saved_usd': round(total_saved, 4),
            'requests': total_requests,
        }

    def _cost_per_cached_token(self, provider: str) -> float:
        """Cache read cost per token for a given provider."""
        return _CACHE_COST_PER_TOKEN.get(provider, 0.0)

    def _cost_saved(self, provider: str, cached_tokens: int) -> float:
        """Cost saved = (full input price - cache read price) × cached tokens."""
        full = _INPUT_COST_PER_TOKEN.get(provider, 0.0)
        cached = _CACHE_COST_PER_TOKEN.get(provider, 0.0)
        return (full - cached) * cached_tokens
