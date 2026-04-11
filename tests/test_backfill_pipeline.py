"""
Tests for the backfill pipeline layer.

These tests exercise ``scripts.backfill.pipeline.process_record`` and
the synthetic source end-to-end against an isolated cairn_intel_test
schema. LLM calls are mocked — the tests verify the pipeline's
control flow (short-circuits, budget consumption, idempotency) but do
NOT reach out to Claude.

If Postgres + pgvector isn't reachable, the module is skipped — the
same pattern as tests/test_counterfactual_memory.py.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from dotenv import load_dotenv

load_dotenv(override=True)

psycopg2 = pytest.importorskip('psycopg2')


TEST_SCHEMA = 'cairn_intel_test_backfill'


def _probe_db() -> str | None:
    dsn = os.getenv('DATABASE_URL', '')
    if not dsn:
        return None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
            if not cur.fetchone():
                return None
    finally:
        conn.close()
    return dsn


_DB_URL = _probe_db()

pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason='Postgres with pgvector not reachable via DATABASE_URL',
)


# Deterministic fake embedder shared with the Phase 1 tests
def _fake_embed(text: str) -> list[float]:
    import hashlib
    import math
    vec = [0.0] * 768
    for word in text.lower().split():
        digest = hashlib.md5(word.encode('utf-8')).digest()
        for i in range(0, 16, 2):
            idx = (digest[i] * 256 + digest[i + 1]) % 768
            vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope='module')
def fresh_schema():
    from core.intel.db import ensure_schema, drop_schema
    drop_schema(db_url=_DB_URL, schema=TEST_SCHEMA)
    ensure_schema(db_url=_DB_URL, schema=TEST_SCHEMA)
    yield TEST_SCHEMA
    drop_schema(db_url=_DB_URL, schema=TEST_SCHEMA)


@pytest.fixture
def memory(fresh_schema):
    from core.intel.memory import CounterfactualMemory
    mem = CounterfactualMemory(
        db_url=_DB_URL,
        embed_fn=_fake_embed,
        schema=fresh_schema,
    )
    with mem._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f'TRUNCATE TABLE {fresh_schema}.decisions CASCADE')
            cur.execute(f'TRUNCATE TABLE {fresh_schema}.backfill_runs')
        conn.commit()
    return mem


@pytest.fixture
def budget():
    from scripts.backfill.llm_budget import LLMBudget
    return LLMBudget(max_sonnet=10, max_opus=5, max_bulk=100)


@pytest.fixture
def mock_tagger(budget):
    """An ArchetypeTagger whose internal client is a MagicMock.

    Pre-tagged records in the synthetic source never reach the real
    Haiku methods, so this only matters if a test deliberately feeds
    in an unt-agged record.
    """
    from scripts.backfill.archetype_tagger import ArchetypeTagger
    tagger = ArchetypeTagger(budget=budget, api_key='test-key')
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(type='text', text='["pricing"]')]
    mock_client.messages.create.return_value = mock_resp
    tagger._client = mock_client
    return tagger


@pytest.fixture
def mock_lesson_gen(budget):
    """A LessonGenerator whose internal client is a MagicMock."""
    from scripts.backfill.lesson_generator import LessonGenerator
    gen = LessonGenerator(budget=budget, api_key='test-key')
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = [
        MagicMock(type='text', text='Mock generated lesson for test.'),
    ]
    mock_client.messages.create.return_value = mock_resp
    gen._client = mock_client
    return gen


# ── Synthetic source sanity ────────────────────────────────────────────


def test_synthetic_source_yields_ten_records():
    from scripts.backfill.sources.synthetic import SyntheticSource
    records = list(SyntheticSource().iter_records())
    assert len(records) == 10
    assert all(r.deterministic_id.startswith('backfill_synthetic_') for r in records)
    assert all(r.context_summary for r in records)
    assert all(r.archetype_tags for r in records)


# ── Pipeline unit tests ────────────────────────────────────────────────


def test_pipeline_dry_run_writes_nothing(memory, mock_tagger, mock_lesson_gen, fresh_schema):
    from scripts.backfill.pipeline import RunContext, process_record
    from scripts.backfill.sources.synthetic import SyntheticSource

    ctx = RunContext(run_id='dry-run-test', dry_run=True)
    for record in SyntheticSource().iter_records():
        result = process_record(record, memory, mock_tagger, mock_lesson_gen, ctx)
        assert result.ok
        assert result.dry_run
        assert result.written is False

    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM {fresh_schema}.decisions')
            assert cur.fetchone()[0] == 0
    assert ctx.counts_per_source == {'synthetic': 10}


def test_pipeline_commit_writes_expected_rows(memory, mock_tagger, mock_lesson_gen, fresh_schema):
    from scripts.backfill.pipeline import RunContext, process_record
    from scripts.backfill.sources.synthetic import SyntheticSource

    run_id = 'commit-test-1'
    memory.start_backfill_run(run_id=run_id, sources_requested=['synthetic'], mode='commit')
    ctx = RunContext(run_id=run_id, dry_run=False)
    for record in SyntheticSource().iter_records():
        result = process_record(record, memory, mock_tagger, mock_lesson_gen, ctx)
        assert result.ok, result.error

    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.decisions '
                f'WHERE backfill_run_id = %s',
                (run_id,),
            )
            assert cur.fetchone()[0] == 10
            # Every synthetic record in the fixture has an outcome,
            # so outcomes should match 1:1.
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.decision_outcomes o '
                f'JOIN {fresh_schema}.decisions d ON o.decision_id = d.id '
                f'WHERE d.backfill_run_id = %s',
                (run_id,),
            )
            assert cur.fetchone()[0] == 10
            # Dissents from rejected_paths — count matches the fixture
            # (dispute_1: 2, dispute_2: 2, b2b_1: 2, b2b_2: 1, b2b_3: 1,
            # mnumber_2: 1, email_1: 1 → 10).
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.module_dissents dis '
                f'JOIN {fresh_schema}.decisions d ON dis.decision_id = d.id '
                f'WHERE d.backfill_run_id = %s',
                (run_id,),
            )
            assert cur.fetchone()[0] == 10
            # One record has needs_privacy_review=True, so committed=FALSE.
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.decisions '
                f'WHERE backfill_run_id = %s AND committed = FALSE',
                (run_id,),
            )
            assert cur.fetchone()[0] == 1


def test_pipeline_verbatim_lesson_uses_toby_verbatim_model(
    memory, mock_tagger, mock_lesson_gen, fresh_schema
):
    from scripts.backfill.pipeline import RunContext, process_record
    from scripts.backfill.sources.synthetic import SyntheticSource

    ctx = RunContext(run_id='verbatim-test', dry_run=False)
    for record in SyntheticSource().iter_records():
        process_record(record, memory, mock_tagger, mock_lesson_gen, ctx)

    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT lesson_model, COUNT(*) '
                f'FROM {fresh_schema}.decision_outcomes '
                f'WHERE lesson IS NOT NULL '
                f'GROUP BY lesson_model ORDER BY lesson_model'
            )
            breakdown = dict(cur.fetchall())
    # 4 verbatim lessons in the fixture: dispute_1, dispute_2, principle_1, principle_2.
    assert breakdown.get('toby_verbatim') == 4
    # The mock lesson generator also runs for records that pass the
    # gate but lack a verbatim lesson (b2b_1, mnumber_1, mnumber_2).
    assert breakdown.get('claude-sonnet-4-6') == 3


def test_pipeline_budget_is_consumed_by_generated_lessons(
    memory, mock_tagger, mock_lesson_gen, fresh_schema, budget
):
    from scripts.backfill.pipeline import RunContext, process_record
    from scripts.backfill.sources.synthetic import SyntheticSource

    assert budget.sonnet_used == 0
    ctx = RunContext(run_id='budget-test', dry_run=False)
    for record in SyntheticSource().iter_records():
        process_record(record, memory, mock_tagger, mock_lesson_gen, ctx)

    # 3 Sonnet calls expected (b2b_1, mnumber_1, mnumber_2).
    assert budget.sonnet_used == 3
    assert budget.opus_used == 0
    # No Haiku calls — the synthetic source pre-populates summary + tags.
    assert budget.bulk_used == 0


def test_pipeline_is_idempotent_across_reruns(
    memory, mock_tagger, mock_lesson_gen, fresh_schema
):
    from scripts.backfill.pipeline import RunContext, process_record
    from scripts.backfill.sources.synthetic import SyntheticSource

    run_id = 'idempotency-test'
    for _ in range(3):
        ctx = RunContext(run_id=run_id, dry_run=False)
        for record in SyntheticSource().iter_records():
            process_record(record, memory, mock_tagger, mock_lesson_gen, ctx)

    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.decisions '
                f'WHERE backfill_run_id = %s',
                (run_id,),
            )
            assert cur.fetchone()[0] == 10
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.decision_outcomes o '
                f'JOIN {fresh_schema}.decisions d ON o.decision_id = d.id '
                f'WHERE d.backfill_run_id = %s',
                (run_id,),
            )
            # After three runs, still 10 outcomes — the pipeline purges
            # old outcomes before re-inserting.
            assert cur.fetchone()[0] == 10
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.module_dissents dis '
                f'JOIN {fresh_schema}.decisions d ON dis.decision_id = d.id '
                f'WHERE d.backfill_run_id = %s',
                (run_id,),
            )
            assert cur.fetchone()[0] == 10


def test_should_generate_lesson_gate():
    from datetime import datetime, timezone
    from scripts.backfill.pipeline import should_generate_lesson
    from scripts.backfill.sources.base import RawHistoricalRecord, RawOutcome

    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # No outcome → False
    r = RawHistoricalRecord(
        deterministic_id='x', source_type='dispute',
        decided_at=base_time, chosen_path='x',
        signal_strength=0.95,
    )
    assert should_generate_lesson(r) is False

    # Low signal strength → False
    r = RawHistoricalRecord(
        deterministic_id='x', source_type='dispute',
        decided_at=base_time, chosen_path='x',
        signal_strength=0.7,
        outcome=RawOutcome(observed_at=base_time, actual_result='...'),
    )
    assert should_generate_lesson(r) is False

    # Dispute, signal>=0.8, outcome → True regardless of score
    r = RawHistoricalRecord(
        deterministic_id='x', source_type='dispute',
        decided_at=base_time, chosen_path='x',
        signal_strength=0.8,
        outcome=RawOutcome(observed_at=base_time, actual_result='...'),
    )
    assert should_generate_lesson(r) is True

    # Other source, high signal, score ≥ 0.7 → True
    r = RawHistoricalRecord(
        deterministic_id='x', source_type='m_number',
        decided_at=base_time, chosen_path='x',
        signal_strength=0.95,
        outcome=RawOutcome(
            observed_at=base_time, actual_result='...',
            chosen_path_score=0.8,
        ),
    )
    assert should_generate_lesson(r) is True

    # Other source, high signal, score 0.5 → False
    r = RawHistoricalRecord(
        deterministic_id='x', source_type='m_number',
        decided_at=base_time, chosen_path='x',
        signal_strength=0.95,
        outcome=RawOutcome(
            observed_at=base_time, actual_result='...',
            chosen_path_score=0.5,
        ),
    )
    assert should_generate_lesson(r) is False


def test_pipeline_calls_tagger_for_untagged_record(memory, mock_tagger, mock_lesson_gen, budget):
    """If a record arrives without archetype_tags, the tagger runs and budget ticks."""
    from datetime import datetime, timezone
    from scripts.backfill.pipeline import RunContext, process_record
    from scripts.backfill.sources.base import RawHistoricalRecord

    ctx = RunContext(run_id='tagger-test', dry_run=False)
    record = RawHistoricalRecord(
        deterministic_id='needs-tag-1',
        source_type='synthetic',
        decided_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        chosen_path='Do the thing',
        raw_text='This is a raw, unsummarised business situation about pricing.',
        # no context_summary → tagger.summarise called
        # no archetype_tags → tagger.tag called
    )
    result = process_record(record, memory, mock_tagger, mock_lesson_gen, ctx)
    assert result.ok, result.error
    assert result.tags == ['pricing']  # from the mock response
    # Two Haiku calls — one summarise + one tag.
    assert budget.bulk_used == 2


def test_privacy_scrub_strips_pii():
    from scripts.backfill import privacy
    text = (
        'Contact John at john.smith@example.co.uk or call 01665 123456. '
        'Based at NE66 1AB. VAT GB123456789.'
    )
    scrubbed = privacy.scrub(text)
    assert 'john.smith@example.co.uk' not in scrubbed
    assert '[EMAIL_REDACTED]' in scrubbed
    assert '[PHONE_REDACTED]' in scrubbed
    assert '[POSTCODE_REDACTED]' in scrubbed
    assert '[VAT_REDACTED]' in scrubbed


def test_llm_budget_raises_when_exhausted():
    from scripts.backfill.llm_budget import LLMBudget, BudgetExceeded

    b = LLMBudget(max_sonnet=1, max_opus=0, max_bulk=2)
    b.consume_sonnet('x')
    with pytest.raises(BudgetExceeded):
        b.consume_sonnet('x')
    b.consume_bulk('x')
    b.consume_bulk('x')
    with pytest.raises(BudgetExceeded):
        b.consume_bulk('x')
    with pytest.raises(BudgetExceeded):
        b.consume_opus('x')


def test_preflight_fails_when_data_file_missing(tmp_path):
    from scripts.backfill.run import preflight
    # disputes requires data/disputes.yml — pass an empty tmp_path
    failures = preflight(sources=['disputes'], data_dir=tmp_path, commit_mode=False)
    assert any('disputes.yml' in f for f in failures)


def test_preflight_passes_for_synthetic(tmp_path):
    from scripts.backfill.run import preflight
    failures = preflight(sources=['synthetic'], data_dir=tmp_path, commit_mode=False)
    assert failures == []
