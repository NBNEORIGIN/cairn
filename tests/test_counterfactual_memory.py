"""
Tests for ``core.intel`` — the counterfactual memory module.

These are integration tests: they target a real Postgres database with
the pgvector extension installed, because the retrieval behaviour we
care about (cosine similarity ranking, ivfflat / exact search) is
entirely in the database.

Each test runs in a throwaway schema ``cairn_intel_test`` that is
dropped and recreated by the session fixture, so tests never touch the
production ``cairn_intel`` schema.

If a Postgres + pgvector database isn't reachable the whole module is
skipped — CI without a DB still runs cleanly.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from dotenv import load_dotenv

load_dotenv()

psycopg2 = pytest.importorskip('psycopg2')

TEST_SCHEMA = 'cairn_intel_test'


# ── DB availability probe ──────────────────────────────────────────────


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
            row = cur.fetchone()
            if not row:
                return None
    finally:
        conn.close()
    return dsn


_DB_URL = _probe_db()

pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason='Postgres with pgvector not reachable via DATABASE_URL',
)


# ── Deterministic fake embedder ────────────────────────────────────────
#
# The production embedder is real Ollama / OpenAI. For tests we want
# deterministic, repeatable 768-dim vectors that *do* differentiate by
# content, so that similarity ranking is testable. We hash characters
# into buckets and normalise.


def _fake_embed(text: str) -> list[float]:
    import hashlib

    vec = [0.0] * 768
    words = text.lower().split()
    for word in words:
        # Stable per-word offset + value from md5
        digest = hashlib.md5(word.encode('utf-8')).digest()
        for i in range(0, 16, 2):
            idx = (digest[i] * 256 + digest[i + 1]) % 768
            vec[idx] += 1.0

    # L2 normalise so cosine distance is meaningful
    import math
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope='module')
def fresh_schema():
    """Create a throwaway ``cairn_intel_test`` schema for the module run."""
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
    # Wipe rows between tests; keep schema.
    with mem._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f'TRUNCATE TABLE {fresh_schema}.decisions CASCADE')
            cur.execute(f'TRUNCATE TABLE {fresh_schema}.backfill_runs')
        conn.commit()
    return mem


# ── Tests ──────────────────────────────────────────────────────────────


def test_ensure_schema_is_idempotent(fresh_schema):
    """Running ensure_schema twice must not raise or drop rows."""
    from core.intel.db import ensure_schema

    ensure_schema(db_url=_DB_URL, schema=fresh_schema)
    ensure_schema(db_url=_DB_URL, schema=fresh_schema)

    import psycopg2 as p
    conn = p.connect(_DB_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = '{fresh_schema}'
                ORDER BY table_name
                """
            )
            tables = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    assert 'decisions' in tables
    assert 'decision_outcomes' in tables
    assert 'module_dissents' in tables
    assert 'backfill_runs' in tables


def test_record_historical_decision_is_idempotent(memory, fresh_schema):
    """Calling twice with the same id updates rather than duplicating."""
    when = datetime(2024, 5, 1, tzinfo=timezone.utc)

    memory.record_historical_decision(
        decision_id='backfill_dispute_evri-2024_phase1',
        source_type='dispute',
        decided_at=when,
        context_summary='Evri claimed damage to parcel worth £1705.',
        archetype_tags=['adversarial', 'time_pressured', 'pricing'],
        chosen_path='Rejected the first offer',
        signal_strength=0.95,
    )

    memory.record_historical_decision(
        decision_id='backfill_dispute_evri-2024_phase1',
        source_type='dispute',
        decided_at=when,
        context_summary='Evri claimed damage to parcel worth £1705 — updated narrative.',
        archetype_tags=['adversarial', 'time_pressured'],
        chosen_path='Rejected the first offer, countered at £350',
        signal_strength=0.95,
    )

    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*), MAX(context_summary), MAX(chosen_path) '
                f'FROM {fresh_schema}.decisions'
            )
            count, summary, chosen = cur.fetchone()
    assert count == 1
    assert 'updated narrative' in summary
    assert 'countered at £350' in chosen


def test_embedding_is_computed_non_null(memory, fresh_schema):
    memory.record_historical_decision(
        decision_id='decision-with-embed',
        source_type='principle',
        decided_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        context_summary='Never undercut your own Amazon listings on Etsy.',
        archetype_tags=['pricing', 'repeated_game'],
        chosen_path='Hold the Etsy price',
    )
    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT embedding IS NOT NULL '
                f'FROM {fresh_schema}.decisions WHERE id = %s',
                ('decision-with-embed',),
            )
            assert cur.fetchone()[0] is True


def test_signal_strength_clamped(memory, fresh_schema):
    memory.record_historical_decision(
        decision_id='clamp-negative',
        source_type='synthetic',
        decided_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        context_summary='Negative signal attempt.',
        archetype_tags=['one_shot'],
        chosen_path='x',
        signal_strength=-0.5,
    )
    memory.record_historical_decision(
        decision_id='clamp-high',
        source_type='synthetic',
        decided_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        context_summary='Too-high signal attempt.',
        archetype_tags=['one_shot'],
        chosen_path='x',
        signal_strength=7.3,
    )
    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT id, signal_strength FROM {fresh_schema}.decisions '
                f'WHERE id IN (%s, %s) ORDER BY id',
                ('clamp-high', 'clamp-negative'),
            )
            rows = dict(cur.fetchall())
    assert rows['clamp-negative'] == pytest.approx(0.0)
    assert rows['clamp-high'] == pytest.approx(1.0)


def test_retrieve_similar_ranks_adversarial_above_cooperative(memory):
    """The core promise: structurally similar decisions rank higher."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)

    memory.record_historical_decision(
        decision_id='adv-pricing-1',
        source_type='dispute',
        decided_at=base,
        context_summary=(
            'Hostile client demanded a 40 percent price cut on a '
            'signage quote under threat of cancellation.'
        ),
        archetype_tags=['adversarial', 'pricing', 'time_pressured'],
        chosen_path='Held the price, offered a smaller sign instead',
        signal_strength=0.9,
    )
    memory.record_historical_decision(
        decision_id='adv-pricing-2',
        source_type='b2b_quote',
        decided_at=base + timedelta(days=10),
        context_summary=(
            'Aggressive negotiation over signage quote, buyer '
            'threatened to walk if pricing not reduced.'
        ),
        archetype_tags=['adversarial', 'pricing', 'one_shot'],
        chosen_path='Refused reduction, quote went cold',
        signal_strength=0.9,
    )
    memory.record_historical_decision(
        decision_id='coop-ops-1',
        source_type='m_number',
        decided_at=base + timedelta(days=20),
        context_summary=(
            'Routine production scheduling between two cooperating '
            'suppliers over a lamination run.'
        ),
        archetype_tags=['cooperative', 'operational'],
        chosen_path='Split the run across two days',
        signal_strength=0.9,
    )

    results = memory.retrieve_similar(
        query=(
            'New quote where the buyer is aggressively demanding a '
            'discount and threatening to cancel the signage order.'
        ),
        top_k=3,
    )
    assert len(results) == 3
    top_ids = [r['decision_id'] for r in results[:2]]
    assert 'adv-pricing-1' in top_ids
    assert 'adv-pricing-2' in top_ids
    # The cooperative operational decision must rank last
    assert results[-1]['decision_id'] == 'coop-ops-1'
    # And its similarity must be strictly lower than the adversarial ones
    assert results[-1]['similarity'] < results[0]['similarity']
    assert results[-1]['similarity'] < results[1]['similarity']


def test_retrieve_excludes_uncommitted_rows(memory):
    base = datetime(2024, 6, 1, tzinfo=timezone.utc)
    memory.record_historical_decision(
        decision_id='pending-email-1',
        source_type='email',
        decided_at=base,
        context_summary='Aggressive price negotiation over quote.',
        archetype_tags=['adversarial', 'pricing'],
        chosen_path='Held price',
        committed=False,
    )
    memory.record_historical_decision(
        decision_id='committed-email-1',
        source_type='email',
        decided_at=base,
        context_summary='Aggressive price negotiation over quote.',
        archetype_tags=['adversarial', 'pricing'],
        chosen_path='Held price',
        committed=True,
    )
    results = memory.retrieve_similar(
        query='aggressive price negotiation',
        top_k=5,
    )
    ids = [r['decision_id'] for r in results]
    assert 'committed-email-1' in ids
    assert 'pending-email-1' not in ids


def test_promote_pending_flips_committed(memory):
    base = datetime(2024, 6, 1, tzinfo=timezone.utc)
    memory.record_historical_decision(
        decision_id='pending-2',
        source_type='email',
        decided_at=base,
        context_summary='Quote context.',
        archetype_tags=['pricing'],
        chosen_path='x',
        committed=False,
    )
    n = memory.promote_pending(['pending-2'])
    assert n == 1

    results = memory.retrieve_similar(query='quote context', top_k=5)
    assert any(r['decision_id'] == 'pending-2' for r in results)

    # Second call should be a no-op now that the row is already committed.
    assert memory.promote_pending(['pending-2']) == 0


def test_backfill_run_linkage(memory, fresh_schema):
    run_id = f'backfill-test-{uuid.uuid4().hex[:8]}'
    memory.start_backfill_run(
        run_id=run_id,
        sources_requested=['disputes', 'principles'],
        mode='commit',
    )
    base = datetime(2024, 2, 1, tzinfo=timezone.utc)
    for i in range(3):
        memory.record_historical_decision(
            decision_id=f'{run_id}-decision-{i}',
            source_type='dispute',
            decided_at=base + timedelta(days=i),
            context_summary=f'Test decision {i} about an adversarial quote.',
            archetype_tags=['adversarial', 'pricing'],
            chosen_path=f'Choice {i}',
            backfill_run_id=run_id,
        )
    memory.finish_backfill_run(
        run_id=run_id,
        status='complete',
        counts_per_source={'disputes': 3},
        claude_calls_used=0,
        bulk_llm_calls_used=6,
    )

    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.decisions '
                f'WHERE backfill_run_id = %s',
                (run_id,),
            )
            assert cur.fetchone()[0] == 3
            cur.execute(
                f'SELECT status, counts_per_source '
                f'FROM {fresh_schema}.backfill_runs WHERE id = %s',
                (run_id,),
            )
            status, counts = cur.fetchone()
            assert status == 'complete'
            assert counts == {'disputes': 3}


def test_outcome_and_lesson_attached(memory, fresh_schema):
    base = datetime(2024, 3, 1, tzinfo=timezone.utc)
    memory.record_historical_decision(
        decision_id='decision-outcome-1',
        source_type='dispute',
        decided_at=base,
        context_summary='Dispute with courier over alleged damage.',
        archetype_tags=['adversarial', 'time_pressured'],
        chosen_path='Rejected initial offer',
        signal_strength=0.95,
    )
    outcome_id = memory.record_outcome(
        decision_id='decision-outcome-1',
        observed_at=base + timedelta(days=30),
        actual_result='Settled at £350 six weeks later.',
        chosen_path_score=0.8,
        metrics={'settlement_gbp': 350, 'days_to_resolve': 45},
    )
    assert outcome_id > 0

    memory.attach_lesson(
        outcome_id=outcome_id,
        lesson='Never accept the first settlement offer from a courier.',
        lesson_model='toby_verbatim',
    )

    results = memory.retrieve_similar(
        query='courier disputing damage claim',
        top_k=3,
    )
    assert any(r['decision_id'] == 'decision-outcome-1' for r in results)
    hit = next(r for r in results if r['decision_id'] == 'decision-outcome-1')
    assert hit['outcome'] is not None
    assert 'Settled at £350' in hit['outcome']['actual_result']
    assert hit['outcome']['lesson_model'] == 'toby_verbatim'
    assert 'first settlement offer' in hit['outcome']['lesson']


def test_record_dissent(memory, fresh_schema):
    base = datetime(2024, 4, 1, tzinfo=timezone.utc)
    memory.record_historical_decision(
        decision_id='decision-dissent-1',
        source_type='b2b_quote',
        decided_at=base,
        context_summary='Three-option quote for bakery signage.',
        archetype_tags=['pricing', 'cooperative'],
        chosen_path='Middle option: aluminium with vinyl graphics',
        rejected_paths=[
            {'path': 'Cheapest: foamex only', 'reason': 'Would not last outdoors'},
            {'path': 'Premium: built-up letters', 'reason': 'Over budget'},
        ],
    )
    memory.record_dissent(
        decision_id='decision-dissent-1',
        module='historical_toby',
        argued_for='Cheapest: foamex only',
        argument='Would not last outdoors',
    )
    memory.record_dissent(
        decision_id='decision-dissent-1',
        module='historical_toby',
        argued_for='Premium: built-up letters',
        argument='Over budget',
    )
    with memory._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM {fresh_schema}.module_dissents '
                f'WHERE decision_id = %s',
                ('decision-dissent-1',),
            )
            assert cur.fetchone()[0] == 2


def test_retrieve_filter_by_source_type(memory):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    memory.record_historical_decision(
        decision_id='src-dispute',
        source_type='dispute',
        decided_at=base,
        context_summary='Aggressive negotiation over quote.',
        archetype_tags=['adversarial', 'pricing'],
        chosen_path='x',
    )
    memory.record_historical_decision(
        decision_id='src-principle',
        source_type='principle',
        decided_at=base,
        context_summary='Aggressive negotiation over quote.',
        archetype_tags=['adversarial', 'pricing'],
        chosen_path='x',
    )
    results = memory.retrieve_similar(
        query='aggressive negotiation quote',
        top_k=10,
        include_sources=['principle'],
    )
    ids = [r['decision_id'] for r in results]
    assert 'src-principle' in ids
    assert 'src-dispute' not in ids
