"""Unit tests for core.memory.impressions — rerank + reinforcement."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core.memory.impressions import (
    _min_max,
    _hours_since,
    rerank,
    shadow_enabled,
)


class TestMinMax:
    def test_empty(self):
        assert _min_max([]) == []

    def test_constant_collapses_to_zero(self):
        # When all candidates have the same value, normalisation is
        # meaningless — we return zeros (neutral) rather than NaN.
        assert _min_max([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]

    def test_normal_range(self):
        out = _min_max([0.0, 5.0, 10.0])
        assert out == [0.0, 0.5, 1.0]

    def test_negative(self):
        out = _min_max([-1.0, 0.0, 1.0])
        assert out == [0.0, 0.5, 1.0]


class TestHoursSince:
    def test_none_returns_large(self):
        assert _hours_since(None) > 1e5

    def test_now_returns_near_zero(self):
        now = datetime.now(timezone.utc)
        assert _hours_since(now) < 0.01

    def test_24h_ago(self):
        past = datetime.now(timezone.utc) - timedelta(hours=24)
        h = _hours_since(past)
        assert 23.9 < h < 24.1

    def test_iso_string_parse(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        h = _hours_since(past)
        assert 11.9 < h < 12.1


class TestShadowEnabled:
    def test_unset_defaults_true(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DEEK_IMPRESSIONS_SHADOW', None)
            assert shadow_enabled() is True

    def test_explicit_false(self):
        with patch.dict(os.environ, {'DEEK_IMPRESSIONS_SHADOW': 'false'}):
            assert shadow_enabled() is False

    def test_explicit_true(self):
        with patch.dict(os.environ, {'DEEK_IMPRESSIONS_SHADOW': 'true'}):
            assert shadow_enabled() is True


class TestRerank:
    def _mk(self, chunk_id, salience, hours_old, rrf=0.5, chunk_type='memory'):
        return {
            'chunk_id': chunk_id,
            'salience': salience,
            'last_accessed_at': (
                datetime.now(timezone.utc) - timedelta(hours=hours_old)
            ),
            'chunk_type': chunk_type,
            'dedupe_key': f'c{chunk_id}',
            'file': f'f{chunk_id}',
            'content': f'content for chunk {chunk_id}',
            'rrf_score': rrf,
        }

    def test_empty_candidates(self):
        out, dbg = rerank([])
        assert out == []
        assert dbg == []

    def test_uniform_inputs_identity(self):
        """When salience + recency are uniform, the rerank must collapse
        to relevance-only — identity on equal RRF scores (stable sort)."""
        cands = [self._mk(i, 1.0, 0.1, rrf=0.5) for i in range(3)]
        out, _ = rerank(cands)
        # All scores equal — order preserved (stable sort)
        assert [c['chunk_id'] for c in out] == [0, 1, 2]

    def test_higher_salience_wins_when_relevance_equal(self):
        # All same RRF, same recency, different salience → higher salience ranks first
        cands = [
            self._mk(0, 1.0, 0.1),
            self._mk(1, 5.0, 0.1),
            self._mk(2, 10.0, 0.1),
        ]
        out, _ = rerank(cands)
        assert [c['chunk_id'] for c in out] == [2, 1, 0]

    def test_fresher_wins_when_relevance_and_salience_equal(self):
        # All same salience + RRF, different recency → fresher ranks first
        cands = [
            self._mk(0, 5.0, 100.0),  # older
            self._mk(1, 5.0, 1.0),    # fresh
            self._mk(2, 5.0, 24.0),
        ]
        out, _ = rerank(cands)
        assert out[0]['chunk_id'] == 1
        assert out[-1]['chunk_id'] == 0

    def test_attaches_impressions_score(self):
        cands = [self._mk(i, 1.0 + i, i * 10) for i in range(3)]
        out, _ = rerank(cands)
        for c in out:
            assert 'impressions_score' in c
            assert 0.0 <= c['impressions_score'] <= 1.0

    def test_debug_breakdown(self):
        cands = [self._mk(i, 1.0 + i, i * 10) for i in range(3)]
        _, dbg = rerank(cands)
        assert len(dbg) == 3
        for d in dbg:
            assert 0.0 <= d.rel_n <= 1.0
            assert 0.0 <= d.sal_n <= 1.0
            assert 0.0 <= d.rec_n <= 1.0

    def test_custom_weights_all_salience(self):
        # alpha=0, beta=1, gamma=0 → rank by salience only
        cands = [
            self._mk(0, 1.0, 1.0, rrf=0.9),  # high rrf but low salience
            self._mk(1, 10.0, 1.0, rrf=0.1), # low rrf but high salience
        ]
        out, _ = rerank(
            cands,
            rrf_scores=[0.9, 0.1],
            config={'alpha': 0.0, 'beta': 1.0, 'gamma': 0.0, 'tau_hours': 72.0,
                    'top_k': 20},
        )
        assert out[0]['chunk_id'] == 1  # salience won


# ── Reinforcement tests (DB-free, mock-based) ─────────────────────────

class TestReinforceAsync:
    def test_empty_list_is_noop(self):
        from core.memory.impressions import reinforce_async
        # Should return instantly, no error
        reinforce_async([])

    def test_none_ids_filtered(self):
        from core.memory.impressions import reinforce_async
        # Should not raise even with None-valued ids
        reinforce_async([None, None])

    def test_graceful_no_db(self):
        """Without DATABASE_URL, reinforcement must be a silent no-op."""
        from core.memory.impressions import _reinforce_sync
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DATABASE_URL', None)
            # Should not raise even though there's no DB configured.
            _reinforce_sync([1, 2, 3])
