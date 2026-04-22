"""Tests for core.models.validation_messages.

Verifies the three user-safety invariants:

  1. No CHECK codes leak through user_facing_fallback
  2. No raw exception strings leak through user_reason_for_error/timeout
  3. retry_guidance_for_failures produces CHECK-specific bullets
     that can be fed back to the model

Plus Brief-1a.2-style regression: multi-check + unknown-check +
timeout paths all terminate with a short plain-English sentence.
"""
from __future__ import annotations

import pytest

from core.models.validation_messages import (
    retry_guidance_for_failures,
    user_facing_fallback,
    user_reason_for_error,
    user_reason_for_failures,
    user_reason_for_timeout,
)


class TestUserReasonForFailures:
    def test_empty(self):
        reason = user_reason_for_failures([])
        assert 'CHECK' not in reason
        assert reason  # not empty string

    def test_single_check_3(self):
        reason = user_reason_for_failures(
            ['CHECK 3: hallucinated file path "core/memory/brief_questions.py"']
        )
        assert 'CHECK' not in reason
        assert 'brief_questions' not in reason
        assert 'verify' in reason.lower() or 'file' in reason.lower()

    def test_single_check_2(self):
        reason = user_reason_for_failures(['CHECK 2: refusal detected ("as an ai")'])
        assert 'CHECK' not in reason
        assert 'as an ai' not in reason.lower()

    def test_multi_check(self):
        reason = user_reason_for_failures([
            'CHECK 3: hallucinated file path "x.py"',
            'CHECK 5: empty or near-empty response',
        ])
        assert 'CHECK' not in reason
        assert 'multiple' in reason.lower()

    def test_unknown_check_number(self):
        # CHECK 99 is not in the mapping — should still be user-safe
        reason = user_reason_for_failures(['CHECK 99: some new check fired'])
        assert 'CHECK' not in reason
        assert reason

    def test_unparseable_failure_line(self):
        reason = user_reason_for_failures(['something weird that is not a check'])
        assert 'CHECK' not in reason

    def test_case_insensitive_check_parsing(self):
        reason = user_reason_for_failures(['check 3: lowercase variant'])
        # Parser handles case-insensitively
        assert 'CHECK' not in reason


class TestUserFacingFallback:
    def test_never_contains_check_code(self):
        for n in (1, 2, 3, 4, 5, 6, 99):
            reason = user_reason_for_failures([f'CHECK {n}: whatever'])
            msg = user_facing_fallback(reason)
            assert 'CHECK' not in msg
            assert 'check ' + str(n) not in msg.lower() or 'check' not in msg.lower()

    def test_shape(self):
        msg = user_facing_fallback('I cited a file I could not verify.')
        assert "wasn't able" in msg.lower() or "was not able" in msg.lower()
        assert 'rephrase' in msg.lower() or 'narrow' in msg.lower()


class TestTimeoutAndErrorReasons:
    def test_timeout_no_leak(self):
        r = user_reason_for_timeout()
        assert 'TimeoutError' not in r
        assert 'exception' not in r.lower()
        assert r

    def test_error_ignores_exception(self):
        exc = RuntimeError('internal database handle pointer null at 0xDEADBEEF')
        r = user_reason_for_error(exc)
        assert 'RuntimeError' not in r
        assert 'DEADBEEF' not in r
        assert 'database handle' not in r


class TestRetryGuidance:
    def test_check_3_guidance(self):
        g = retry_guidance_for_failures(['CHECK 3: hallucinated file path "x.py"'])
        assert 'file' in g.lower()
        assert 'verif' in g.lower()

    def test_check_5_guidance(self):
        g = retry_guidance_for_failures(['CHECK 5: empty or near-empty response'])
        assert 'empty' in g.lower() or 'complete' in g.lower()

    def test_check_2_guidance(self):
        g = retry_guidance_for_failures(['CHECK 2: refusal detected'])
        assert 'refuse' in g.lower() or 'directly' in g.lower()

    def test_multi_check_guidance_has_both(self):
        g = retry_guidance_for_failures([
            'CHECK 3: bad path',
            'CHECK 5: empty',
        ])
        # Both bullets present
        assert g.count('\n-') >= 2 or g.count('- ') >= 2

    def test_unknown_check_returns_empty(self):
        assert retry_guidance_for_failures([]) == ''
        assert retry_guidance_for_failures(['CHECK 99: unknown']) == ''
        assert retry_guidance_for_failures(['garbage']) == ''


# ── Regression: the specific leak shapes that existed pre-fix ─────────

class TestLeakShapeRegression:
    """The old agent.py returned strings starting with 'Validation failed:'
    and containing 'CHECK <n>:' codes verbatim. The new user-facing
    fallback must produce neither."""

    @pytest.mark.parametrize('failures', [
        ['CHECK 3: hallucinated file path "core/memory/brief_questions.py"'],
        ['CHECK 1: tool description without execution ("i would call")'],
        ['CHECK 6: syntax error in foo.py: unexpected indent (line 3)'],
        ['CHECK 5: empty or near-empty response',
         'CHECK 3: hallucinated file path "x.py"'],
    ])
    def test_no_leak(self, failures):
        reason = user_reason_for_failures(failures)
        msg = user_facing_fallback(reason)
        assert not msg.startswith('Validation failed')
        assert 'CHECK' not in msg
        # No raw path leak either
        assert '.py"' not in msg
        assert 'core/memory' not in msg
