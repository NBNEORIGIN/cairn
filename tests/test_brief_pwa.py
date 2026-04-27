"""Unit + endpoint-shape tests for api.routes.brief_pwa.

The DB-dependent path (apply_reply mutating schemas, store_response
writing audit rows) is exercised live on Hetzner; this suite covers
the helpers and the FastAPI endpoint contracts via TestClient with
a fake DB connection.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.routes import brief_pwa


# ── Helper unit tests ───────────────────────────────────────────────


class TestQuestionIdRoundTrip:
    def test_format(self):
        assert brief_pwa._question_id(1) == 'q1'
        assert brief_pwa._question_id(7) == 'q7'

    def test_parse_valid(self):
        assert brief_pwa._parse_question_id('q1') == 1
        assert brief_pwa._parse_question_id('Q12') == 12

    def test_parse_invalid(self):
        assert brief_pwa._parse_question_id('') is None
        assert brief_pwa._parse_question_id('1') is None
        assert brief_pwa._parse_question_id('qABC') is None
        assert brief_pwa._parse_question_id('q0') is None


class TestNormaliseQuestions:
    def test_list_passthrough(self):
        raw = [{'category': 'open_ended', 'prompt': 'X'}]
        assert brief_pwa._normalise_questions(raw) == raw

    def test_string_json(self):
        raw = '[{"category": "hr_pulse", "prompt": "Y"}]'
        out = brief_pwa._normalise_questions(raw)
        assert out == [{'category': 'hr_pulse', 'prompt': 'Y'}]

    def test_none(self):
        assert brief_pwa._normalise_questions(None) == []

    def test_invalid_json_string(self):
        assert brief_pwa._normalise_questions('not json') == []

    def test_drops_non_dict_items(self):
        raw = [{'a': 1}, 'string', None, {'b': 2}]
        out = brief_pwa._normalise_questions(raw)
        assert out == [{'a': 1}, {'b': 2}]


# ── Fake DB plumbing ────────────────────────────────────────────────


class _FakeCursor:
    """Cursor that returns scripted results in order. Tests assemble
    a list of (sql_substring, result) pairs and the cursor matches
    the next one each execute() call."""

    def __init__(self, scripted: list[tuple[str, object]]):
        self._scripted = list(scripted)
        self._next: object = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if not self._scripted:
            self._next = None
            return
        # Match the first scripted entry whose substring is in the sql
        for i, (frag, result) in enumerate(self._scripted):
            if frag in sql:
                self._next = result
                self._scripted.pop(i)
                return
        # No match — return empty result
        self._next = None

    def fetchone(self):
        v = self._next
        if isinstance(v, list):
            return v[0] if v else None
        return v

    def fetchall(self):
        v = self._next
        if isinstance(v, list):
            return v
        return [v] if v else []


class _FakeConn:
    def __init__(self, scripted: list[tuple[str, object]]):
        self._scripted = scripted

    def cursor(self):
        return _FakeCursor(self._scripted)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def headers():
    return {
        'X-API-Key': os.environ.get(
            'DEEK_API_KEY', 'deek-dev-key-change-in-production',
        ),
    }


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


# ── /today endpoint ─────────────────────────────────────────────────


class TestBriefToday:
    def test_404_when_no_brief(self, client, headers, monkeypatch):
        # Cursor returns None for the run lookup
        fake = _FakeConn(scripted=[('FROM memory_brief_runs', None)])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)
        r = client.get(
            '/api/deek/brief/today?user=jo@example.com',
            headers=headers,
        )
        assert r.status_code == 404
        assert r.json()['detail'] == 'no_brief_today'

    def test_returns_brief_unanswered(self, client, headers, monkeypatch):
        run_row = (
            '11111111-1111-1111-1111-111111111111',
            datetime(2026, 4, 27, 7, 32, tzinfo=timezone.utc),
            'Deek morning brief — 2026-04-27',
            [
                {'category': 'hr_pulse', 'prompt': 'Anything?', 'reply_format': 'free text'},
                {'category': 'open_ended', 'prompt': 'Worth remembering?', 'reply_format': 'free text'},
            ],
        )
        fake = _FakeConn(scripted=[
            ('FROM memory_brief_runs', run_row),
            ('FROM memory_brief_responses', None),
        ])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)

        r = client.get(
            '/api/deek/brief/today?user=jo@example.com',
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['brief_id'] == '11111111-1111-1111-1111-111111111111'
        assert data['date'] == '2026-04-27'
        assert data['answered'] is False
        assert data['answers'] == []
        assert len(data['questions']) == 2
        assert data['questions'][0]['id'] == 'q1'
        assert data['questions'][0]['category'] == 'hr_pulse'
        assert data['questions'][1]['id'] == 'q2'

    def test_returns_brief_answered(self, client, headers, monkeypatch):
        run_row = (
            '22222222-2222-2222-2222-222222222222',
            datetime(2026, 4, 27, 7, 32, tzinfo=timezone.utc),
            'Subject',
            [{'category': 'open_ended', 'prompt': 'X', 'reply_format': ''}],
        )
        response_row = (
            {'answers': [{
                'q_number': 1, 'category': 'open_ended',
                'verdict': 'correct', 'correction_text': 'Yes — kept',
            }]},
            {'channel': 'pwa'},
            datetime(2026, 4, 27, 9, 0, tzinfo=timezone.utc),
        )
        fake = _FakeConn(scripted=[
            ('FROM memory_brief_runs', run_row),
            ('FROM memory_brief_responses', response_row),
        ])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)

        r = client.get(
            '/api/deek/brief/today?user=jo@example.com',
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['answered'] is True
        assert len(data['answers']) == 1
        assert data['answers'][0]['question_id'] == 'q1'
        assert data['answers'][0]['correction_text'] == 'Yes — kept'


# ── /reply endpoint ─────────────────────────────────────────────────


class TestBriefReply:
    def test_400_no_brief_id(self, client, headers):
        r = client.post(
            '/api/deek/brief/reply',
            headers=headers,
            json={'answers': [{'question_id': 'q1', 'text': 'hi'}]},
        )
        assert r.status_code == 400
        assert r.json()['detail'] == 'brief_id_required'

    def test_400_no_answers(self, client, headers):
        r = client.post(
            '/api/deek/brief/reply',
            headers=headers,
            json={'brief_id': 'abc', 'answers': []},
        )
        assert r.status_code == 400
        assert r.json()['detail'] == 'answers_required'

    def test_404_when_brief_missing(self, client, headers, monkeypatch):
        fake = _FakeConn(scripted=[('FROM memory_brief_runs', None)])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)
        r = client.post(
            '/api/deek/brief/reply',
            headers=headers,
            json={
                'brief_id': '00000000-0000-0000-0000-000000000000',
                'answers': [{'question_id': 'q1', 'text': 'hi'}],
            },
        )
        assert r.status_code == 404
        assert r.json()['detail'] == 'brief_not_found'

    def test_400_when_no_answers_recognised(
        self, client, headers, monkeypatch,
    ):
        # Brief exists but the submitted question_id doesn't match
        run_row = (
            'jo@example.com',
            datetime(2026, 4, 27, tzinfo=timezone.utc),
            [{'category': 'open_ended', 'prompt': 'X', 'provenance': {}}],
        )
        fake = _FakeConn(scripted=[('FROM memory_brief_runs', run_row)])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)

        r = client.post(
            '/api/deek/brief/reply',
            headers=headers,
            json={
                'brief_id': '00000000-0000-0000-0000-000000000000',
                'answers': [{'question_id': 'q99', 'text': 'orphan'}],
            },
        )
        assert r.status_code == 400
        assert r.json()['detail'] == 'no_answers_recognised'

    def test_happy_path_marks_pwa_channel(
        self, client, headers, monkeypatch,
    ):
        run_row = (
            'jo@example.com',
            datetime(2026, 4, 27, tzinfo=timezone.utc),
            [
                {'category': 'open_ended', 'prompt': 'X', 'provenance': {}},
                {'category': 'hr_pulse', 'prompt': 'Y', 'provenance': {}},
            ],
        )
        fake = _FakeConn(scripted=[('FROM memory_brief_runs', run_row)])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)

        # Stub the pieces that would otherwise hit the DB
        monkeypatch.setattr(
            'core.brief.replies.already_applied',
            lambda conn, run_id, raw: False,
        )
        captured: dict = {}

        def fake_apply_reply(conn, parsed_reply):
            captured['parsed'] = parsed_reply
            return {
                'user_email': parsed_reply.user_email,
                'run_date': parsed_reply.run_date.isoformat(),
                'answers_processed': [
                    {'q_number': a.q_number, 'category': a.category,
                     'verdict': a.verdict, 'action': 'wrote'}
                    for a in parsed_reply.answers
                ],
                'parse_notes': parsed_reply.parse_notes,
            }

        monkeypatch.setattr(
            'core.brief.replies.apply_reply',
            fake_apply_reply,
        )
        monkeypatch.setattr(
            'core.brief.replies.store_response',
            lambda conn, run_id, raw, parsed, summary: 'response-uuid',
        )

        r = client.post(
            '/api/deek/brief/reply',
            headers=headers,
            json={
                'brief_id': '00000000-0000-0000-0000-000000000000',
                'answers': [
                    {'question_id': 'q1', 'text': 'kept'},
                    {'question_id': 'q2', 'text': 'nothing today'},
                ],
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data['ok'] is True
        assert data['idempotent'] is False
        assert data['response_id'] == 'response-uuid'
        assert data['applied_summary']['channel'] == 'pwa'
        assert data['applied_summary']['source'] == 'pwa_brief_reply'

        # The apply_reply stub captured the ParsedReply we constructed
        parsed = captured['parsed']
        assert parsed.user_email == 'jo@example.com'
        assert len(parsed.answers) == 2
        assert parsed.answers[0].q_number == 1
        assert parsed.answers[0].category == 'open_ended'
        assert parsed.answers[1].q_number == 2
        assert parsed.answers[1].category == 'hr_pulse'

    def test_idempotent_replay_returns_short_circuit(
        self, client, headers, monkeypatch,
    ):
        run_row = (
            'jo@example.com',
            datetime(2026, 4, 27, tzinfo=timezone.utc),
            [{'category': 'open_ended', 'prompt': 'X', 'provenance': {}}],
        )
        fake = _FakeConn(scripted=[('FROM memory_brief_runs', run_row)])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)
        monkeypatch.setattr(
            'core.brief.replies.already_applied',
            lambda conn, run_id, raw: True,
        )

        # apply_reply must NOT be called on idempotent replay
        def boom(*a, **kw):
            raise AssertionError('apply_reply should not be called')

        monkeypatch.setattr('core.brief.replies.apply_reply', boom)

        r = client.post(
            '/api/deek/brief/reply',
            headers=headers,
            json={
                'brief_id': '00000000-0000-0000-0000-000000000000',
                'answers': [{'question_id': 'q1', 'text': 'kept'}],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data['idempotent'] is True
        assert data['applied_summary']['channel'] == 'pwa'


# ── /memory/recent endpoint ─────────────────────────────────────────


class TestMemoryRecent:
    def test_returns_filtered_items(self, client, headers, monkeypatch):
        rows = [
            (
                42,
                'Toby open-ended reflection: keep the supplier',
                'Toby open-ended reflection: keep the supplier — they always deliver',
                datetime(2026, 4, 27, 9, 30, tzinfo=timezone.utc),
                7.0,
                {'via': 'memory_brief_reply', 'toby_flag': 1.0},
            ),
        ]
        fake = _FakeConn(scripted=[('FROM claw_code_chunks', rows)])
        monkeypatch.setattr(brief_pwa, '_connect', lambda: fake)

        r = client.get(
            '/api/deek/brief/memory/recent?user=jo@example.com&limit=5',
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data['count'] == 1
        assert data['items'][0]['id'] == 42
        assert data['items'][0]['via'] == 'memory_brief_reply'
        assert data['items'][0]['salience'] == 7.0
