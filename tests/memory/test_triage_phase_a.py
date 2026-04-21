"""Unit tests for Triage Phase A — candidate matching + drafter +
digest format.

DB-dependent paths (runner + DB upsert) are exercised by the live
dry-run on Hetzner; these tests cover the pure logic so the
discipline is enforced regardless of infrastructure state.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── Project matcher: top-N candidate shape ──────────────────────────

class TestProjectMatcher:
    """The matcher now returns a `candidates` list with up to 3
    entries. Confident top match still populates `project_id` at the
    top level for backwards compatibility."""

    def _fake_response(self, status: int, results: list[dict]):
        class _R:
            def __init__(self, s, d):
                self.status_code = s
                self._data = d
            def json(self):
                return {'results': self._data}
            @property
            def text(self):
                import json as _j
                return _j.dumps({'results': self._data})
        return _R(status, results)

    def test_empty_results(self, monkeypatch):
        from scripts.email_triage import project_matcher
        monkeypatch.setenv('DEEK_API_KEY', 'test-key')

        class _Client:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, *a, **k):
                return self._resp
        _Client._resp = self._fake_response(200, [])
        with patch('httpx.Client', _Client):
            out = project_matcher.match_project(
                email={'subject': 's', 'sender': 'x@y'},
                classifier_result={},
            )
        assert out == {
            'project_id': '', 'match_score': 0.0,
            'project_name': '', 'candidates': [],
        }

    def test_top_three_candidates_returned(self, monkeypatch):
        from scripts.email_triage import project_matcher
        monkeypatch.setenv('DEEK_API_KEY', 'test-key')

        results = [
            {
                'source_id': 'p1', 'source_type': 'project',
                'score': 0.08,
                'metadata': {'project_name': 'Flowers By Julie shopfront',
                             'last_activity_at': '2026-04-15',
                             'status': 'quoted'},
                'excerpt': 'First excerpt about the job',
            },
            {
                'source_id': 'p2', 'source_type': 'project',
                'score': 0.04,
                'metadata': {'project_name': 'Julie Flowers shop refresh',
                             'status': 'draft'},
                'excerpt': 'Second excerpt',
            },
            {
                'source_id': 'p3', 'source_type': 'project',
                'score': 0.02,
                'metadata': {'project_name': 'Third project'},
                'excerpt': 'Third excerpt',
            },
            {
                'source_id': 'p4', 'source_type': 'project',
                'score': 0.01,
                'metadata': {'project_name': 'Beyond top-N'},
                'excerpt': 'Should not appear',
            },
        ]

        class _Client:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, *a, **k):
                return self._resp
        _Client._resp = self._fake_response(200, results)
        with patch('httpx.Client', _Client):
            out = project_matcher.match_project(
                email={'subject': 'Re: shopfront', 'sender': 'julie@example'},
                classifier_result={'client_name_guess': 'Flowers By Julie'},
            )
        assert len(out['candidates']) == 3
        assert out['candidates'][0]['project_id'] == 'p1'
        assert out['candidates'][0]['project_name'] == 'Flowers By Julie shopfront'
        assert out['candidates'][1]['project_id'] == 'p2'
        # Threshold was lowered to 0.015 — 0.08 clears it
        assert out['project_id'] == 'p1'
        assert out['match_score'] == pytest.approx(0.08)

    def test_below_threshold_still_surfaces_candidates(self, monkeypatch):
        """When the top score is below MIN_MATCH_SCORE, project_id
        is blank but candidates list is still populated — so the
        digest can show alternatives even for weak matches."""
        from scripts.email_triage import project_matcher
        monkeypatch.setenv('DEEK_API_KEY', 'test-key')

        results = [
            {
                'source_id': 'weak1', 'source_type': 'project',
                'score': 0.010, 'metadata': {}, 'excerpt': 'weak',
            },
        ]
        class _Client:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, *a, **k):
                return self._resp
        _Client._resp = self._fake_response(200, results)
        with patch('httpx.Client', _Client):
            out = project_matcher.match_project(
                email={'subject': 's', 'sender': 'x@y'},
                classifier_result={},
            )
        assert out['project_id'] == ''        # below threshold
        assert len(out['candidates']) == 1    # but surfaced anyway
        assert out['candidates'][0]['project_id'] == 'weak1'


# ── Response drafter: prompt assembly + parsing ─────────────────────

class TestDrafterPromptAssembly:
    def test_includes_voice_rules_candidate(self):
        from scripts.email_triage.response_drafter import _build_prompt
        email = {
            'sender': 'julie@example.com',
            'subject': 'Re: shopfront quote',
            'body_text': 'Could we go ahead?',
        }
        candidate = {
            'project_id': 'p1',
            'project_name': 'Flowers By Julie shopfront',
            'match_score': 0.082,
        }
        tone = {
            'voice': {'description': 'Plain and friendly.'},
            'rules': ['Never invent prices'],
            'length': {'target_words': 80, 'max_words': 180},
        }
        prompt = _build_prompt(email, candidate, 'prior history here', tone, False)
        assert 'Plain and friendly.' in prompt
        assert 'Never invent prices' in prompt
        assert 'Could we go ahead?' in prompt
        assert 'Flowers By Julie' in prompt
        # Reply format contract — drafter must emit JSON
        assert '"draft":' in prompt

    def test_low_confidence_shortens_target(self):
        from scripts.email_triage.response_drafter import _build_prompt
        tone = {'length': {'target_words': 80, 'low_confidence_target_words': 40, 'max_words': 180}}
        prompt_normal = _build_prompt(
            {'body_text': 'hi'}, None, '', tone, False,
        )
        prompt_low = _build_prompt(
            {'body_text': 'hi'}, None, '', tone, True,
        )
        assert 'Target around 80' in prompt_normal
        assert 'Target around 40' in prompt_low

    def test_strips_reply_quoted_tail(self):
        from scripts.email_triage.response_drafter import _build_prompt
        email = {
            'body_text': (
                'My fresh reply\n\n'
                '> Original old content\n'
                '> More old content\n'
            ),
        }
        prompt = _build_prompt(email, None, '', {}, False)
        assert 'My fresh reply' in prompt
        assert 'Original old content' not in prompt

    def test_no_candidate_renders_no_match(self):
        from scripts.email_triage.response_drafter import _build_prompt
        prompt = _build_prompt(
            {'body_text': 'anything'}, None, '', {}, False,
        )
        assert 'none found above the confidence bar' in prompt


class TestDrafterResponseParsing:
    def test_happy_path(self):
        from scripts.email_triage.response_drafter import _parse_response
        raw = (
            '{"draft": "Hi Julie, happy to proceed. Best, Toby",'
            ' "confidence": "high", "needs_followup": false,'
            ' "notes": ""}'
        )
        draft, confidence, notes = _parse_response(raw)
        assert 'Hi Julie' in draft
        assert confidence == 'high'
        assert notes == ''

    def test_prose_wrapped_json(self):
        from scripts.email_triage.response_drafter import _parse_response
        raw = (
            'Here is the draft:\n\n'
            '{"draft": "Short reply", "confidence": "medium", "notes": "n"}\n\n'
            'Hope that helps.'
        )
        draft, confidence, _ = _parse_response(raw)
        assert draft == 'Short reply'
        assert confidence == 'medium'

    def test_empty_draft_rejected(self):
        """A JSON object with an empty draft is treated as no-draft;
        the caller's DraftResult.text will be empty."""
        from scripts.email_triage.response_drafter import _parse_response
        draft, confidence, _ = _parse_response(
            '{"draft": "", "confidence": "none", "notes": "not enough context"}'
        )
        # Parse succeeds but draft text is empty — handled by caller.
        assert draft == ''
        assert confidence == 'none'

    def test_malformed_json(self):
        from scripts.email_triage.response_drafter import _parse_response
        draft, confidence, notes = _parse_response('not json at all')
        assert draft == ''
        assert confidence == 'none'
        assert 'JSON' in notes or 'no JSON' in notes

    def test_empty(self):
        from scripts.email_triage.response_drafter import _parse_response
        assert _parse_response('')[0] == ''


# ── Digest format blocks ────────────────────────────────────────────

class TestDigestBlocks:
    def test_candidates_block_with_list(self):
        from scripts.email_triage.digest_sender import _build_candidates_block
        row = {
            'match_candidates': [
                {
                    'project_id': 'p1',
                    'project_name': 'Flowers By Julie',
                    'match_score': 0.08,
                    'last_activity_at': '2026-04-15T10:00:00',
                    'status': 'quoted',
                    'excerpt': 'first line\nsecond line',
                },
                {
                    'project_id': 'p2',
                    'project_name': 'Julie Garden Centre',
                    'match_score': 0.03,
                    'excerpt': '',
                },
            ],
        }
        lines = _build_candidates_block(row)
        body = '\n'.join(lines)
        assert 'CANDIDATE PROJECTS' in body
        assert 'Flowers By Julie' in body
        assert '-> 1.' in body                # winner gets the arrow
        assert '   2.' in body               # second has no arrow
        assert 'score:    0.080' in body      # formatted score
        assert 'Julie Garden Centre' in body
        # Excerpt rendered for the first candidate only (has content)
        assert '| first line' in body

    def test_candidates_block_legacy_fallback(self):
        """When match_candidates is empty but project_id exists
        (legacy path), render the single-id block."""
        from scripts.email_triage.digest_sender import _build_candidates_block
        lines = _build_candidates_block({'project_id': 'legacy-id'})
        body = '\n'.join(lines)
        assert 'PROJECT MATCH' in body
        assert 'legacy-id' in body

    def test_candidates_block_no_match(self):
        from scripts.email_triage.digest_sender import _build_candidates_block
        lines = _build_candidates_block({})
        body = '\n'.join(lines)
        assert 'no match found' in body

    def test_draft_block_with_text(self):
        from scripts.email_triage.digest_sender import _build_draft_block
        lines = _build_draft_block({
            'draft_reply': 'Hi Julie,\n\nHappy to proceed.\n\nBest,\nToby',
            'draft_model': 'qwen2.5:7b-instruct',
        })
        body = '\n'.join(lines)
        assert 'PROPOSED REPLY' in body
        assert 'Hi Julie' in body
        assert 'qwen2.5:7b-instruct' in body

    def test_draft_block_no_text(self):
        from scripts.email_triage.digest_sender import _build_draft_block
        lines = _build_draft_block({'draft_reply': ''})
        body = '\n'.join(lines)
        assert 'no draft' in body

    def test_reply_back_block_has_four_questions(self):
        from scripts.email_triage.digest_sender import _build_reply_back_block
        lines = _build_reply_back_block({})
        body = '\n'.join(lines)
        assert '--- Q1 (match_confirm) ---' in body
        assert '--- Q2 (reply_approval) ---' in body
        assert '--- Q3 (project_folder) ---' in body
        assert '--- Q4 (notes) ---' in body
        # Matches the existing Memory Brief reply-back shape — Phase B
        # parser will reuse the same delimiter format.


# ── Tone config loader ──────────────────────────────────────────────

class TestToneLoader:
    def test_loads_real_file(self):
        from scripts.email_triage.response_drafter import _load_tone
        tone = _load_tone()
        # The canonical file ships in config/email_triage/
        assert tone
        assert 'voice' in tone
        assert 'rules' in tone

    def test_missing_file_returns_empty(self, monkeypatch):
        monkeypatch.setenv('DEEK_RESPONSE_TONE', '/non/existent/path.yaml')
        # Need to reload the module so the new env var is picked up
        import importlib
        import scripts.email_triage.response_drafter as rd
        importlib.reload(rd)
        assert rd._load_tone() == {}
