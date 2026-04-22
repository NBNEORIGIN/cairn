"""Tests for core.intel.quote_context.

Stubs the CRM HTTP API + Ollama. Pins:
  - empty-input graceful paths
  - margin_reference math (small N, median, range)
  - deterministic signal detection (margin delta, late payments, risk)
  - shadow-mode gating (shadow on → returns 'ok' regardless)
  - shadow log write on real-verdict path
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.intel.quote_context import (
    _compute_signals,
    _margin_reference,
    _extract_payment_hints,
    get_quote_context,
    is_quote_review_shadow,
    review_draft_quote,
    search_similar_quotes,
)


# ── Margin reference math ────────────────────────────────────────────

class TestMarginReference:
    def test_too_few_samples_returns_none(self):
        assert _margin_reference([]) is None
        assert _margin_reference([100.0]) is None
        assert _margin_reference([100.0, 200.0]) is None

    def test_three_samples_ok(self):
        out = _margin_reference([100.0, 200.0, 300.0])
        assert out is not None
        assert out['sample_size'] == 3
        assert out['quoted_range_median'] == 200.0

    def test_ignores_zero_and_negative(self):
        out = _margin_reference([0, -50, 100, 200, 300])
        assert out is not None
        assert out['sample_size'] == 3

    def test_range_monotone(self):
        out = _margin_reference([100, 150, 200, 250, 300, 400, 600])
        assert out is not None
        assert out['quoted_range_low'] <= out['quoted_range_median']
        assert out['quoted_range_median'] <= out['quoted_range_high']


# ── Signal detection ────────────────────────────────────────────────

class TestSignals:
    def _ctx(self, median=None, payment=None):
        return {
            'margin_reference': (
                {'quoted_range_median': median} if median else None
            ),
            'client': {'payment_record': payment or {}},
        }

    def test_margin_below_threshold_flags(self):
        # total is 40% below median
        sigs = _compute_signals(self._ctx(median=1000), 600, '')
        assert any('below' in s for s in sigs)

    def test_margin_above_threshold_flags(self):
        # total is 50% above median
        sigs = _compute_signals(self._ctx(median=1000), 1500, '')
        assert any('above' in s for s in sigs)

    def test_margin_within_band_no_flag(self):
        # 5% below median — no flag
        sigs = _compute_signals(self._ctx(median=1000), 950, '')
        assert not any('margin_vs_median' in s for s in sigs)

    def test_margin_no_median_no_flag(self):
        sigs = _compute_signals(self._ctx(), 500, '')
        assert not any('margin_vs_median' in s for s in sigs)

    def test_late_payments_flag(self):
        sigs = _compute_signals(
            self._ctx(payment={'late_count': 3}), None, '',
        )
        assert any('late_payments' in s for s in sigs)

    def test_single_late_no_flag(self):
        sigs = _compute_signals(
            self._ctx(payment={'late_count': 1}), None, '',
        )
        assert not any('late_payments' in s for s in sigs)

    def test_high_risk_band_flags(self):
        sigs = _compute_signals(
            self._ctx(payment={'risk_band': 'HIGH'}), None, '',
        )
        assert any('risk_band' in s for s in sigs)
        sigs = _compute_signals(
            self._ctx(payment={'risk_band': 'CRITICAL'}), None, '',
        )
        assert any('risk_band' in s for s in sigs)

    def test_low_risk_band_no_flag(self):
        sigs = _compute_signals(
            self._ctx(payment={'risk_band': 'LOW'}), None, '',
        )
        assert not any('risk_band' in s for s in sigs)


# ── Payment hint extraction ─────────────────────────────────────────

class TestPaymentHints:
    def test_metadata_passthrough(self):
        md = {'risk_band': 'HIGH', 'late_count': 2, 'noise': 'x'}
        out = _extract_payment_hints(md, '')
        assert out['risk_band'] == 'HIGH'
        assert out['late_count'] == 2
        assert 'noise' not in out

    def test_regex_pulls_late(self):
        out = _extract_payment_hints({}, 'we saw 3 late payments this year')
        assert out['late_count'] == 3

    def test_regex_pulls_risk_band(self):
        out = _extract_payment_hints({}, 'current risk band: MEDIUM')
        assert out['risk_band'] == 'MEDIUM'

    def test_no_signals_returns_none(self):
        assert _extract_payment_hints({}, 'nothing useful here') is None


# ── Shadow gate ─────────────────────────────────────────────────────

class TestShadowGate:
    def test_default_on(self, monkeypatch):
        monkeypatch.delenv('DEEK_QUOTE_REVIEW_SHADOW', raising=False)
        assert is_quote_review_shadow() is True

    def test_false(self, monkeypatch):
        monkeypatch.setenv('DEEK_QUOTE_REVIEW_SHADOW', 'false')
        assert is_quote_review_shadow() is False


# ── CRM stubs for context / similar / review ────────────────────────

def _fake_crm(responses: dict):
    """responses maps search query-prefix → payload dict."""
    class _R:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = json.dumps(payload)
        def raise_for_status(self):
            pass
        def json(self):
            return self._payload

    class _C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None, **k):
            q = (params or {}).get('q', '')
            for prefix, payload in responses.items():
                if q.startswith(prefix):
                    return _R(payload)
            return _R({'results': []})
        def post(self, *a, **k):
            return _R({'message': {'content': '{}'}})

    return _C


class TestGetQuoteContext:
    def test_empty_project_id(self):
        ctx = get_quote_context('')
        assert ctx['project_id'] == ''
        assert ctx['similar_jobs'] == []

    def test_no_token(self, monkeypatch):
        for var in ('DEEK_API_KEY', 'CAIRN_API_KEY', 'CLAW_API_KEY'):
            monkeypatch.delenv(var, raising=False)
        ctx = get_quote_context('proj-1')
        assert 'DEEK_API_KEY' in ctx['warnings'][0]

    def test_happy_path(self, monkeypatch):
        monkeypatch.setenv('DEEK_API_KEY', 'tok')
        project_row = {
            'results': [{
                'source_id': 'proj-1',
                'source_type': 'project',
                'title': 'Flowers by Julie',
                'content': 'Internal fascia signs for Flowers by Julie',
                'metadata': {
                    'project_name': 'Flowers by Julie',
                    'client': 'Flowers by Julie',
                    'stage': 'QUOTED', 'value': 2850,
                },
                'score': 0.8,
            }],
        }
        # For the client-block query we return one client row + a sibling project
        client_rows = {
            'results': [
                {'source_type': 'client',
                 'content': 'Client: Flowers by Julie, 1 late payment, risk band: LOW',
                 'metadata': {}, 'source_id': 'client-1'},
                {'source_type': 'project',
                 'source_id': 'prior-1',
                 'metadata': {
                     'client': 'Flowers by Julie',
                     'project_name': 'Earlier fascia job',
                     'stage': 'WON', 'value': 1900},
                 'score': 0.5},
            ],
        }
        responses = {
            'proj-1': project_row,
            'Flowers': client_rows,
            'Internal fascia': client_rows,  # lessons/similar_jobs use this too
        }
        with patch('httpx.Client', _fake_crm(responses)):
            # Stub out similar_jobs + qwen to keep test deterministic
            with patch('core.triage.similar_jobs.find_similar_jobs',
                       return_value=[]):
                ctx = get_quote_context('proj-1')
        assert ctx['project_id'] == 'proj-1'
        assert ctx['client']['name'] == 'Flowers by Julie'
        assert len(ctx['client']['prior_quotes']) == 1
        assert ctx['client']['prior_quotes'][0]['total'] == 1900.0


class TestSearchSimilarQuotes:
    def test_empty_query(self):
        assert search_similar_quotes('') == []

    def test_no_token(self, monkeypatch):
        for var in ('DEEK_API_KEY', 'CAIRN_API_KEY', 'CLAW_API_KEY'):
            monkeypatch.delenv(var, raising=False)
        assert search_similar_quotes('x') == []

    def test_happy(self, monkeypatch):
        monkeypatch.setenv('DEEK_API_KEY', 'tok')
        responses = {
            '': {'results': [
                {'source_id': 'p-1', 'source_type': 'project',
                 'title': 'Fascia job', 'content': 'Line 1; Line 2',
                 'metadata': {'project_name': 'Fascia job',
                              'client': 'Someone',
                              'stage': 'WON', 'value': 2000},
                 'score': 0.7},
            ]},
        }
        with patch('httpx.Client', _fake_crm(responses)):
            out = search_similar_quotes('coffee shop fascia', limit=5)
        assert len(out) == 1
        assert out[0]['total'] == 2000.0
        assert out[0]['status'] == 'won'


# ── review_draft_quote shadow mode ──────────────────────────────────

class TestReviewDraftQuote:
    def test_shadow_on_returns_ok_regardless(self, monkeypatch):
        monkeypatch.setenv('DEEK_QUOTE_REVIEW_SHADOW', 'true')
        monkeypatch.setenv('DEEK_API_KEY', 'tok')
        # Stub get_quote_context so we don't hit CRM
        fake_ctx = {
            'project_id': 'p1',
            'margin_reference': {'quoted_range_median': 1000.0,
                                 'sample_size': 5,
                                 'quoted_range_low': 800,
                                 'quoted_range_high': 1200,
                                 'quoted_range_mean': 1000},
            'client': {'name': 'X', 'payment_record': None,
                       'prior_quotes': []},
            'similar_jobs': [],
            'lessons_learned': [],
        }
        monkeypatch.setattr(
            'core.intel.quote_context.get_quote_context',
            lambda *a, **k: fake_ctx,
        )
        monkeypatch.setattr(
            'core.intel.quote_context._qwen_quote_review',
            lambda *a, **k: {'verdict': 'flag', 'reasoning': 'bad'},
        )
        out = review_draft_quote('p1', 500.0, 'scope', 'items')
        # Shadow → always 'ok'
        assert out['verdict'] == 'ok'
        assert out['shadow_mode'] is True
        # Real verdict surfaced separately
        assert out['shadow_verdict'] == 'flag'

    def test_shadow_off_returns_real(self, monkeypatch):
        monkeypatch.setenv('DEEK_QUOTE_REVIEW_SHADOW', 'false')
        fake_ctx = {
            'project_id': 'p1',
            'margin_reference': {'quoted_range_median': 1000.0,
                                 'sample_size': 5,
                                 'quoted_range_low': 800,
                                 'quoted_range_high': 1200,
                                 'quoted_range_mean': 1000},
            'client': {'name': 'X', 'payment_record': None,
                       'prior_quotes': []},
            'similar_jobs': [],
            'lessons_learned': [],
        }
        monkeypatch.setattr(
            'core.intel.quote_context.get_quote_context',
            lambda *a, **k: fake_ctx,
        )
        monkeypatch.setattr(
            'core.intel.quote_context._qwen_quote_review',
            lambda *a, **k: {'verdict': 'flag',
                             'reasoning': 'margin too low'},
        )
        out = review_draft_quote('p1', 500.0, 'scope', 'items')
        assert out['verdict'] == 'flag'
        assert out['shadow_mode'] is False
        assert 'margin too low' in out['reasoning']

    def test_shadow_override_kwarg(self, monkeypatch):
        monkeypatch.setenv('DEEK_QUOTE_REVIEW_SHADOW', 'true')
        fake_ctx = {
            'project_id': 'p1',
            'margin_reference': None,
            'client': {'name': 'X', 'payment_record': None,
                       'prior_quotes': []},
            'similar_jobs': [],
            'lessons_learned': [],
        }
        monkeypatch.setattr(
            'core.intel.quote_context.get_quote_context',
            lambda *a, **k: fake_ctx,
        )
        monkeypatch.setattr(
            'core.intel.quote_context._qwen_quote_review',
            lambda *a, **k: {'verdict': 'investigate',
                             'reasoning': 'no data'},
        )
        # Override bypasses the env var
        out = review_draft_quote(
            'p1', 500.0, '', '', shadow_override=False,
        )
        assert out['verdict'] == 'investigate'
        assert out['shadow_mode'] is False
