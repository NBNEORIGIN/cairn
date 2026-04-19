"""Unit tests for core.memory.salience."""
from __future__ import annotations

from core.memory.salience import (
    extract_salience,
    score_money,
    score_customer_pushback,
    score_outcome,
    score_toby_flag,
)


class TestMoneySignal:
    def test_empty(self):
        assert score_money('') == 0.0

    def test_no_amount(self):
        assert score_money('hello world') == 0.0

    def test_small_amount_with_symbol(self):
        # £50 is below the £100 floor — scores ~0
        assert score_money('Quote for £50') < 0.1

    def test_medium_amount(self):
        # £5,000 is mid-range — should be ~0.5-0.7
        s = score_money('Won a £5,000 signage project')
        assert 0.3 < s < 0.8

    def test_large_amount(self):
        # £1M hits the top of the scale
        assert score_money('Deal closed at £1,000,000') >= 0.95

    def test_bare_number_half_weight(self):
        # No currency symbol = half weight vs explicit £
        with_sym = score_money('£5000 deal')
        without = score_money('5000 units shipped')
        assert without < with_sym

    def test_k_suffix(self):
        # £5k should equal £5,000
        a = score_money('£5k quote')
        b = score_money('£5,000 quote')
        assert abs(a - b) < 0.05


class TestPushbackSignal:
    def test_no_pushback(self):
        assert score_customer_pushback('Thanks, this looks great') == 0.0

    def test_single_hit(self):
        assert score_customer_pushback(
            "I'm frustrated with the delay"
        ) == 0.2

    def test_multiple_hits_stack(self):
        s = score_customer_pushback(
            "I'm unhappy and want a refund — this is unacceptable"
        )
        assert s == pytest_min(s, 1.0)  # capped
        assert s >= 0.6  # at least 3 hits * 0.2

    def test_case_insensitive(self):
        assert score_customer_pushback('UNACCEPTABLE') > 0
        assert score_customer_pushback('unacceptable') > 0


def pytest_min(a, b):
    return min(a, b)  # helper just to keep assert readable above


class TestOutcomeSignal:
    def test_no_metadata(self):
        assert score_outcome({}) == 0.0

    def test_failures_high(self):
        assert score_outcome({'outcome': 'fail'}) == 1.0
        assert score_outcome({'outcome': 'failed'}) == 1.0

    def test_wins_low(self):
        assert score_outcome({'outcome': 'win'}) == 0.3
        assert score_outcome({'outcome': 'success'}) < 0.5

    def test_unknown_outcome(self):
        assert score_outcome({'outcome': 'weird-status'}) == 0.0


class TestTobyFlag:
    def test_false(self):
        assert score_toby_flag({}) == 0.0
        assert score_toby_flag({'toby_flag': False}) == 0.0

    def test_true(self):
        assert score_toby_flag({'toby_flag': True}) == 1.0
        assert score_toby_flag({'starred': True}) == 1.0


class TestExtractSalience:
    def test_trivial_acknowledgement_low(self):
        r = extract_salience('Thanks, received.', {})
        assert r.score < 2.0
        assert 'money' in r.signals
        assert all(0.0 <= v <= 1.0 for v in r.signals.values())

    def test_expensive_failure_high(self):
        # £5,000 + customer pushback + failure outcome should be well
        # above the baseline. Exact threshold calibrated against the
        # default weights in config/salience.yaml (base 1 + money
        # 1.0 + pushback 0.8 + fail outcome 3.0 ≈ 5.85).
        r = extract_salience(
            "The £5,000 signage job failed — customer is frustrated and wants a refund.",
            {'outcome': 'fail'},
        )
        assert r.score > 5.5
        assert r.signals['money'] > 0
        assert r.signals['customer_pushback'] > 0
        assert r.signals['outcome_weight'] == 1.0

    def test_score_clipped_to_max(self):
        # Every signal maxed + toby flag should still clip to 10.0
        r = extract_salience(
            "£10,000,000 disaster — unacceptable, refund, escalate to legal.",
            {'outcome': 'fail', 'toby_flag': True},
        )
        assert r.score <= 10.0

    def test_score_never_below_base(self):
        r = extract_salience('', {})
        assert r.score >= 1.0  # base

    def test_signals_exposed_for_audit(self):
        r = extract_salience('£5k deal', {'outcome': 'win'})
        for key in ('money', 'customer_pushback', 'outcome_weight', 'novelty', 'toby_flag'):
            assert key in r.signals


class TestNoveltyGracefulDegradation:
    def test_no_embedding_fn(self):
        from core.memory.salience import score_novelty
        assert score_novelty('anything', None, None) == 0.0

    def test_empty_history(self):
        from core.memory.salience import score_novelty
        assert score_novelty('anything', lambda t: [1.0, 2.0, 3.0], []) == 0.0

    def test_identical_history_returns_zero_novelty(self):
        from core.memory.salience import score_novelty
        # Same embedding = cosine 1.0 = novelty 0
        vec = [1.0, 0.0, 0.0]
        assert score_novelty('x', lambda t: vec, [vec]) == 0.0

    def test_orthogonal_history_returns_full_novelty(self):
        from core.memory.salience import score_novelty
        # Orthogonal = cosine 0 = novelty 1
        assert score_novelty('x', lambda t: [1.0, 0.0], [[0.0, 1.0]]) == 1.0
