"""
Synthetic source — 10 pre-tagged fixture records.

Exists so Phase 2 can exercise the end-to-end backfill pipeline
(summary → tag → decision write → outcome → lesson → dissent) without
touching real data or making real LLM calls.

Every record supplies ``context_summary`` and ``archetype_tags``
up front so the pipeline's tagger never runs. A subset carry a
``verbatim_lesson`` so the lesson-attach path is also exercised
without Sonnet/Opus calls.

The pipeline test in tests/test_backfill_pipeline.py uses this source
as its fixture. ``scripts.backfill.run --source synthetic`` also uses
it for the CLI smoke test.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from .base import HistoricalSource, RawHistoricalRecord, RawOutcome


_UTC = timezone.utc


class SyntheticSource:
    """Yields exactly 10 hand-crafted records across the archetype space."""

    name: str = 'synthetic'
    source_type: str = 'synthetic'

    def iter_records(self) -> Iterator[RawHistoricalRecord]:
        yield from _FIXTURE_RECORDS


_FIXTURE_RECORDS: list[RawHistoricalRecord] = [
    # ── Disputes (adversarial / time_pressured) ───────────────────────
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_dispute_1',
        source_type='synthetic',
        decided_at=datetime(2024, 3, 15, tzinfo=_UTC),
        context_summary=(
            'A courier alleged damage to a signage shipment and '
            'demanded the full invoice value as a claim. The first '
            'settlement offer came in low. Decision had to be made '
            'before the insurance window closed.'
        ),
        archetype_tags=['adversarial', 'time_pressured', 'pricing'],
        chosen_path='Rejected the initial offer and countered at a higher figure.',
        rejected_paths=[
            {'path': 'Accept the initial offer', 'reason': 'Would set a precedent for future claims.'},
            {'path': 'Escalate straight to legal', 'reason': 'Too expensive for the size of claim.'},
        ],
        signal_strength=0.95,
        case_id='synthetic_dispute_case_1',
        outcome=RawOutcome(
            observed_at=datetime(2024, 5, 1, tzinfo=_UTC),
            actual_result='Settled six weeks later at roughly 30% above the initial offer.',
            chosen_path_score=0.7,
            metrics={'days_to_resolve': 47},
        ),
        verbatim_lesson=(
            'Never accept the first settlement offer from a courier — '
            'counter once at a credible figure and wait.'
        ),
    ),
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_dispute_2',
        source_type='synthetic',
        decided_at=datetime(2024, 7, 2, tzinfo=_UTC),
        context_summary=(
            'A retail client disputed a batch of printed panels, '
            'claiming colour drift. Photographic evidence was '
            'inconclusive. Client threatened to withhold payment '
            'across three open invoices.'
        ),
        archetype_tags=['adversarial', 'information_asymmetric', 'repeated_game'],
        chosen_path='Offered a partial reprint on the worst panel and invoiced the rest normally.',
        rejected_paths=[
            {'path': 'Reprint everything free', 'reason': 'Unjustified given evidence.'},
            {'path': 'Refuse entirely', 'reason': 'Would have ended a £40k/yr relationship.'},
        ],
        signal_strength=0.9,
        outcome=RawOutcome(
            observed_at=datetime(2024, 8, 15, tzinfo=_UTC),
            actual_result='Client accepted the partial remedy and paid all three invoices.',
            chosen_path_score=0.8,
        ),
        verbatim_lesson=(
            'When evidence is inconclusive and the relationship is '
            'worth more than the invoice, offer a partial remedy '
            'framed as goodwill, not an admission.'
        ),
    ),
    # ── B2B quotes (pricing / cooperative / one_shot) ─────────────────
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_b2b_1',
        source_type='synthetic',
        decided_at=datetime(2024, 9, 10, tzinfo=_UTC),
        context_summary=(
            'Independent bakery requested a quote for an illuminated '
            'shopfront sign with a firm budget ceiling. Three options '
            'presented: cheapest, mid-range with vinyl graphics, and '
            'premium built-up letters.'
        ),
        archetype_tags=['pricing', 'cooperative', 'one_shot'],
        chosen_path='Led with the middle option: aluminium tray with vinyl graphics at exactly budget.',
        rejected_paths=[
            {'path': 'Foamex only', 'reason': 'Would not last two winters outdoors.'},
            {'path': 'Built-up letters', 'reason': 'Over budget by 40%.'},
        ],
        signal_strength=0.85,
        outcome=RawOutcome(
            observed_at=datetime(2024, 10, 5, tzinfo=_UTC),
            actual_result='Client accepted the middle option and paid deposit within a week.',
            chosen_path_score=0.9,
            metrics={'margin_pct': 38},
        ),
    ),
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_b2b_2',
        source_type='synthetic',
        decided_at=datetime(2024, 11, 20, tzinfo=_UTC),
        context_summary=(
            'Small hair salon asked for a quote for a new sign but '
            'pushed hard for a 25% discount in exchange for a '
            'promise of future referrals.'
        ),
        archetype_tags=['pricing', 'adversarial', 'repeated_game'],
        chosen_path='Held full price and offered a small goodwill extra instead.',
        rejected_paths=[
            {'path': 'Accept the 25% discount', 'reason': 'Would set an undercutting precedent on all sign quotes.'},
        ],
        signal_strength=0.8,
        outcome=RawOutcome(
            observed_at=datetime(2024, 12, 15, tzinfo=_UTC),
            actual_result='Client signed at full price. No referrals materialised.',
            chosen_path_score=0.5,
        ),
    ),
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_b2b_3',
        source_type='synthetic',
        decided_at=datetime(2025, 2, 8, tzinfo=_UTC),
        context_summary=(
            'National hotel chain enquired about rebranding six regional '
            'sites simultaneously. The opportunity was lucrative but the '
            'timeline was impossibly short and the specification kept '
            'shifting through the quoting process.'
        ),
        archetype_tags=['pricing', 'time_pressured', 'information_asymmetric'],
        chosen_path='Declined the full six-site job, offered to pilot one site first.',
        rejected_paths=[
            {'path': 'Accept all six sites with contingency pricing', 'reason': 'Scope was too unstable to price honestly.'},
        ],
        signal_strength=0.85,
        outcome=RawOutcome(
            observed_at=datetime(2025, 3, 30, tzinfo=_UTC),
            actual_result='Client rejected the pilot offer and went to a larger competitor. The competitor ran late and over-budget according to trade gossip six months on.',
            chosen_path_score=0.6,
        ),
    ),
    # ── Manufacture (operational / cooperative) ───────────────────────
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_mnumber_1',
        source_type='synthetic',
        decided_at=datetime(2025, 1, 14, tzinfo=_UTC),
        context_summary=(
            'Production scheduling decision: split a 200-unit lamination '
            'run across two days to avoid bottlenecking the clean bench '
            'ahead of an FBA shipment.'
        ),
        archetype_tags=['operational', 'cooperative', 'time_pressured'],
        chosen_path='Split the run across two days to protect the downstream pack stage.',
        signal_strength=0.95,
        outcome=RawOutcome(
            observed_at=datetime(2025, 1, 17, tzinfo=_UTC),
            actual_result='All 200 units shipped on schedule; pack stage was not disrupted.',
            chosen_path_score=0.8,
        ),
    ),
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_mnumber_2',
        source_type='synthetic',
        decided_at=datetime(2025, 2, 3, tzinfo=_UTC),
        context_summary=(
            'Routine production: a new blank was loaded on the Mimaki '
            'without a pre-check, assuming stable supplier quality. '
            'Mid-run the ink adhesion failed on half the batch.'
        ),
        archetype_tags=['operational', 'one_shot'],
        chosen_path='Ran the batch without a first-article check to save 20 minutes.',
        rejected_paths=[
            {'path': 'Pre-check a single panel before running', 'reason': 'Was considered overkill for a known supplier.'},
        ],
        signal_strength=0.95,
        outcome=RawOutcome(
            observed_at=datetime(2025, 2, 3, tzinfo=_UTC),
            actual_result='Half the run had to be stripped and reprinted; cost four hours.',
            chosen_path_score=-0.7,
            metrics={'waste_units': 100},
        ),
    ),
    # ── Principles (standalone wisdom) ────────────────────────────────
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_principle_1',
        source_type='synthetic',
        decided_at=datetime(2023, 6, 1, tzinfo=_UTC),
        context_summary=(
            'Never undercut your own Amazon listings on Etsy — the '
            'platforms serve different buyer segments and competing '
            'with yourself trains buyers to wait for the cheaper one.'
        ),
        archetype_tags=['pricing', 'repeated_game'],
        chosen_path='Hold Etsy pricing above Amazon landed cost even when Etsy is slow.',
        signal_strength=1.0,
        outcome=RawOutcome(
            observed_at=datetime(2023, 6, 1, tzinfo=_UTC),
            actual_result='Principle derived from repeated observation.',
        ),
        verbatim_lesson=(
            'Never undercut your own Amazon listings on Etsy — the '
            'platforms serve different buyer segments and competing '
            'with yourself trains buyers to wait for the cheaper one.'
        ),
    ),
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_principle_2',
        source_type='synthetic',
        decided_at=datetime(2023, 9, 1, tzinfo=_UTC),
        context_summary=(
            'In an adversarial pricing conversation the party with the '
            'credible walk-away position wins. Always know your walk '
            'point before the conversation starts.'
        ),
        archetype_tags=['adversarial', 'pricing', 'information_asymmetric'],
        chosen_path='Before any negotiation, write down the walk-away price and stick to it.',
        signal_strength=1.0,
        outcome=RawOutcome(
            observed_at=datetime(2023, 9, 1, tzinfo=_UTC),
            actual_result='Principle derived from observed negotiation patterns.',
        ),
        verbatim_lesson=(
            'Write down your walk-away price before any negotiation '
            'starts. The side with the credible walk wins.'
        ),
    ),
    # ── Email-shaped synthetic (exercises the privacy path) ───────────
    RawHistoricalRecord(
        deterministic_id='backfill_synthetic_email_1',
        source_type='synthetic',
        decided_at=datetime(2025, 3, 4, tzinfo=_UTC),
        context_summary=(
            'Enquiry thread about a custom signage quote. The buyer '
            'went silent after the quote was sent, returned two weeks '
            'later asking for a 15% discount. Thread resolved as a '
            'declined follow-up.'
        ),
        archetype_tags=['pricing', 'adversarial', 'one_shot'],
        chosen_path='Restated the original price without discount.',
        rejected_paths=[
            {'path': 'Offer a 10% mid-point discount', 'reason': 'Would have validated the delay tactic.'},
        ],
        signal_strength=0.7,
        needs_privacy_scrub=True,
        needs_privacy_review=True,
        outcome=RawOutcome(
            observed_at=datetime(2025, 3, 20, tzinfo=_UTC),
            actual_result='Buyer did not respond. Thread classified as went_silent.',
            chosen_path_score=0.3,
        ),
    ),
]


# Sanity check at import time: exactly 10 records, every one has the
# mandatory fields. Catches drift in the fixture during refactors.
assert len(_FIXTURE_RECORDS) == 10, 'synthetic source must yield exactly 10 records'
for _r in _FIXTURE_RECORDS:
    assert _r.context_summary, f'{_r.deterministic_id} missing context_summary'
    assert _r.archetype_tags, f'{_r.deterministic_id} missing archetype_tags'
    assert _r.chosen_path, f'{_r.deterministic_id} missing chosen_path'
