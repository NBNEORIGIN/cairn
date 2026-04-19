"""Unit tests for Brief 4 Phase C — pure logic only.

The sweep / decay / digest functions are DB-dependent; those are
exercised by the live dry-run on Hetzner. Here we cover the
pure-function surfaces: digest formatting and threshold behaviour.
"""
from __future__ import annotations

from scripts.dream_maintenance import (
    format_digest,
    STALE_DAYS,
    EXPIRED_ALERT_RATE,
    DORMANT_AFTER_DAYS,
    ARCHIVED_AFTER_DAYS,
)


class TestThresholds:
    def test_defaults_sane(self):
        # Sanity — make sure the constants haven't drifted into
        # nonsensical values via a future refactor.
        assert STALE_DAYS == 7
        assert 0 < EXPIRED_ALERT_RATE < 1
        assert DORMANT_AFTER_DAYS < ARCHIVED_AFTER_DAYS
        assert DORMANT_AFTER_DAYS >= 30


class TestDigestFormatting:
    def _base_inputs(self):
        return {
            'sweep': {
                'expired': 0, 'recent_surfaced': 0,
                'expired_rate': 0.0, 'alert': False,
            },
            'decay': {'to_dormant': 0, 'to_archived': 0},
            'last_night': {'latest_date': None},
            'totals': {'active': 0, 'dormant': 0, 'archived': 0},
        }

    def test_empty_run_renders(self):
        i = self._base_inputs()
        body = format_digest(**i)
        assert 'Deek dream-state digest' in body
        assert 'No nocturnal runs on record yet' in body
        assert 'Stale-candidate sweep' in body
        assert 'Schema lifecycle' in body

    def test_alert_appears_when_rate_high(self):
        i = self._base_inputs()
        i['sweep'] = {
            'expired': 5, 'recent_surfaced': 8,
            'expired_rate': 0.625, 'alert': True,
        }
        body = format_digest(**i)
        assert 'EXPIRED RATE' in body

    def test_no_alert_when_rate_low(self):
        i = self._base_inputs()
        i['sweep'] = {
            'expired': 1, 'recent_surfaced': 10,
            'expired_rate': 0.1, 'alert': False,
        }
        body = format_digest(**i)
        assert 'EXPIRED RATE' not in body

    def test_last_night_stats_rendered(self):
        i = self._base_inputs()
        i['last_night'] = {
            'latest_date': '2026-04-19',
            'total': 5, 'surfaced': 3,
            'accepted': 1, 'rejected': 1, 'deferred': 0, 'expired': 0,
        }
        body = format_digest(**i)
        assert '2026-04-19' in body
        assert 'candidates generated: 5' in body
        assert 'surfaced:             3' in body
        assert '1 accepted' in body
        assert '1 rejected' in body

    def test_schema_totals_rendered(self):
        i = self._base_inputs()
        i['totals'] = {'active': 12, 'dormant': 3, 'archived': 1}
        body = format_digest(**i)
        assert 'active:   12' in body
        assert 'dormant: 3' in body
        assert 'archived: 1' in body

    def test_decay_transitions_rendered(self):
        i = self._base_inputs()
        i['decay'] = {'to_dormant': 2, 'to_archived': 1}
        body = format_digest(**i)
        assert 'transitioned this run' in body
        assert '2 → dormant' in body
        assert '1 → archived' in body

    def test_no_transition_line_when_zero(self):
        i = self._base_inputs()
        i['decay'] = {'to_dormant': 0, 'to_archived': 0}
        body = format_digest(**i)
        assert 'transitioned this run' not in body


class TestSMTPConfig:
    def test_missing_creds_returns_none(self, monkeypatch):
        from scripts.dream_maintenance import smtp_config
        monkeypatch.delenv('SMTP_HOST', raising=False)
        monkeypatch.delenv('SMTP_USER', raising=False)
        monkeypatch.delenv('SMTP_PASS', raising=False)
        assert smtp_config() is None

    def test_partial_creds_returns_none(self, monkeypatch):
        from scripts.dream_maintenance import smtp_config
        monkeypatch.setenv('SMTP_HOST', 'smtp.example.com')
        monkeypatch.setenv('SMTP_USER', 'user')
        monkeypatch.delenv('SMTP_PASS', raising=False)
        assert smtp_config() is None

    def test_full_creds_returns_config(self, monkeypatch):
        from scripts.dream_maintenance import smtp_config
        monkeypatch.setenv('SMTP_HOST', 'smtp.example.com')
        monkeypatch.setenv('SMTP_USER', 'user')
        monkeypatch.setenv('SMTP_PASS', 'pass')
        monkeypatch.setenv('SMTP_PORT', '587')
        cfg = smtp_config()
        assert cfg is not None
        assert cfg['host'] == 'smtp.example.com'
        assert cfg['port'] == 587
        assert cfg['user'] == 'user'
