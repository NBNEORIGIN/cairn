"""Tests for core.triage.thread_association."""
from __future__ import annotations

import pytest

from core.triage.thread_association import (
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_HIGH_AUTO,
    CONFIDENCE_INFERRED,
    CONFIDENCE_MANUAL_TAG,
    SOURCE_TELEGRAM_TAG,
    SOURCE_TRIAGE_REPLY_YES,
    lookup_project_for_thread,
    record_association,
    recent_associations_for_user,
    revoke_association,
)


# ── Fake DB ─────────────────────────────────────────────────────────

class _Cur:
    def __init__(self):
        self.sqls: list[str] = []
        self.params: list[tuple] = []
        self.fetchone_queue: list = []
        self.fetchall_queue: list = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        self.params.append(params)

    def fetchone(self):
        return self.fetchone_queue.pop(0) if self.fetchone_queue else None

    def fetchall(self):
        return self.fetchall_queue.pop(0) if self.fetchall_queue else []

    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def __init__(self):
        self.cur = _Cur()
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


# ── record_association ──────────────────────────────────────────────

class TestRecordAssociation:
    def test_fresh_insert(self):
        conn = _Conn()
        # SELECT existing → None ; INSERT → returns [42]
        conn.cur.fetchone_queue = [None, [42]]
        out = record_association(
            conn,
            thread_id='<msg-a@x>',
            project_id='proj-1',
            source=SOURCE_TRIAGE_REPLY_YES,
            confidence=CONFIDENCE_CONFIRMED,
            associated_by='toby@nbnesigns.com',
        )
        assert out == 42
        assert conn.committed == 1

    def test_higher_confidence_overrides(self):
        conn = _Conn()
        # Existing has LOW confidence, new has HIGH → UPDATE
        conn.cur.fetchone_queue = [[1, CONFIDENCE_INFERRED]]
        out = record_association(
            conn,
            thread_id='<msg-a@x>',
            project_id='proj-1',
            source=SOURCE_TELEGRAM_TAG,
            confidence=CONFIDENCE_MANUAL_TAG,  # rank 3 > inferred rank 1
        )
        assert out == 1
        # Find the UPDATE sql
        assert any('UPDATE' in s and 'confidence = %s' in s
                   for s in conn.cur.sqls)

    def test_same_or_lower_confidence_no_override(self):
        conn = _Conn()
        # Existing has CONFIRMED (rank 4), new comes as HIGH_AUTO (rank 2)
        conn.cur.fetchone_queue = [[1, CONFIDENCE_CONFIRMED]]
        out = record_association(
            conn,
            thread_id='<msg-a@x>',
            project_id='proj-1',
            source='auto_high_confidence',
            confidence=CONFIDENCE_HIGH_AUTO,
        )
        assert out == 1
        # Should be a last_message_at UPDATE (not a confidence change)
        updates = [s for s in conn.cur.sqls if 'UPDATE' in s]
        assert len(updates) == 1
        assert 'last_message_at = NOW()' in updates[0]

    def test_missing_required_fields(self):
        conn = _Conn()
        assert record_association(
            conn, thread_id='', project_id='p',
            source=SOURCE_TRIAGE_REPLY_YES,
        ) is None
        assert record_association(
            conn, thread_id='t', project_id='',
            source=SOURCE_TRIAGE_REPLY_YES,
        ) is None

    def test_unknown_confidence_coerced_to_inferred(self):
        conn = _Conn()
        conn.cur.fetchone_queue = [None, [10]]
        out = record_association(
            conn, thread_id='t', project_id='p',
            source=SOURCE_TRIAGE_REPLY_YES,
            confidence='wtf',
        )
        assert out == 10
        # Verify it wrote CONFIDENCE_INFERRED (rank 1) to the DB
        insert_params = [p for s, p in zip(conn.cur.sqls, conn.cur.params)
                         if 'INSERT' in s][0]
        assert insert_params[2] == CONFIDENCE_INFERRED

    def test_db_error_rolls_back(self):
        class _FailCur:
            def execute(self, *a, **k):
                raise RuntimeError('db dead')
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _FailConn(_Conn):
            def cursor(self):
                return _FailCur()
        conn = _FailConn()
        assert record_association(
            conn, thread_id='t', project_id='p',
            source=SOURCE_TRIAGE_REPLY_YES,
        ) is None
        assert conn.rolled_back == 1


# ── lookup_project_for_thread ───────────────────────────────────────

class TestLookupProjectForThread:
    def test_returns_top_confidence(self):
        conn = _Conn()
        conn.cur.fetchone_queue = [
            [5, '<msg-a@x>', 'proj-1', CONFIDENCE_CONFIRMED,
             SOURCE_TRIAGE_REPLY_YES, 'toby@nbnesigns.com', None],
        ]
        out = lookup_project_for_thread(conn, '<msg-a@x>')
        assert out is not None
        assert out.project_id == 'proj-1'
        assert out.confidence == CONFIDENCE_CONFIRMED

    def test_none_when_missing(self):
        conn = _Conn()
        conn.cur.fetchone_queue = [None]
        assert lookup_project_for_thread(conn, '<msg-b@x>') is None

    def test_empty_thread_id(self):
        conn = _Conn()
        assert lookup_project_for_thread(conn, '') is None
        assert conn.cur.sqls == []

    def test_db_error_returns_none(self):
        class _FailConn(_Conn):
            def cursor(self):
                class _C:
                    def execute(self, *a, **k):
                        raise RuntimeError('dead')
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _C()
        assert lookup_project_for_thread(_FailConn(), 't') is None


# ── revoke_association ──────────────────────────────────────────────

class TestRevokeAssociation:
    def test_revoke_by_thread_only(self):
        conn = _Conn()
        conn.cur.rowcount = 2
        count = revoke_association(
            conn, thread_id='<msg-a@x>',
            revoked_by='toby@nbnesigns.com', reason='wrong project',
        )
        assert count == 2
        # Should not have WHERE project_id = ... clause
        sql = conn.cur.sqls[0]
        assert 'project_id' not in sql.lower() or 'WHERE project_id' not in sql

    def test_revoke_by_thread_and_project(self):
        conn = _Conn()
        conn.cur.rowcount = 1
        count = revoke_association(
            conn, thread_id='<msg-a@x>', project_id='proj-1',
        )
        assert count == 1
        assert 'project_id = %s' in conn.cur.sqls[0]

    def test_no_thread_id_returns_0(self):
        conn = _Conn()
        assert revoke_association(conn, thread_id=None) == 0
        assert conn.cur.sqls == []


# ── recent_associations_for_user ────────────────────────────────────

class TestRecentAssociations:
    def test_user_filter(self):
        conn = _Conn()
        conn.cur.fetchall_queue = [[
            [1, 't1', 'p1', CONFIDENCE_CONFIRMED, 'x', 'toby', None],
            [2, 't2', 'p2', CONFIDENCE_MANUAL_TAG, 'y', 'toby', None],
        ]]
        out = recent_associations_for_user(conn, 'toby@nbnesigns.com', 5)
        assert len(out) == 2
        assert out[0].project_id == 'p1'
        assert 'associated_by = %s' in conn.cur.sqls[0]

    def test_no_user_filter(self):
        conn = _Conn()
        conn.cur.fetchall_queue = [[]]
        out = recent_associations_for_user(conn, None, 3)
        assert out == []
        # SELECT list naturally includes associated_by; we're checking
        # the WHERE clause doesn't filter by it
        assert 'associated_by = %s' not in conn.cur.sqls[0]
