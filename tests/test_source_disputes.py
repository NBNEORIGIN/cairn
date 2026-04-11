"""
Tests for ``scripts.backfill.sources.disputes``.

Builds a small YAML fixture in a tmp_path and exercises the parser +
the Opus upgrade path (for cases with no verbatim lesson) and the
verbatim route (for cases where Toby wrote one).
"""
from __future__ import annotations

from pathlib import Path

import pytest


_FIXTURE_YAML = """\
# Two cases: one with a verbatim lesson, one without.
- case_id: evri-example-2024
  parties: [NBNE, Evri, ExampleClient]
  initial_claim_gbp: 1705
  final_settlement_gbp: 350
  phases:
    - phase: initial_response
      decided_at: 2024-03-15
      context: |
        The courier alleged damage on a high-value shipment and
        demanded the full invoice value as a claim. The initial
        settlement offer came in low. The decision had to be made
        before the insurance window closed.
      chosen_path: "Rejected the first settlement offer of GBP300."
      rejected_alternatives:
        - path: "Accept GBP300 immediately"
          reason: "Would have set a precedent for future claims."
        - path: "Counter at GBP1200"
          reason: "Too high to be credible and risked escalation."
      outcome: |
        Settled six weeks later at GBP350.
      chosen_path_score: 0.7
      metrics:
        settlement_gbp: 350
        days_to_resolve: 45
    - phase: escalation
      decided_at: 2024-04-05
      context: |
        After the first rejection the courier escalated the dispute
        and threatened to pass it to a collections agency.
      chosen_path: "Held position and documented the case for ombudsman review."
      outcome: |
        Courier backed down and proposed a revised number.
      chosen_path_score: 0.6
  lessons_in_your_own_words: |
    Never accept the first settlement offer from a courier —
    counter once at a credible figure and wait.

# A case with no verbatim lesson. The importer will upgrade this
# single lesson call to Opus at the last phase.
- case_id: retail-colour-drift-2024
  parties: [NBNE, RetailClient]
  phases:
    - phase: initial_complaint
      decided_at: 2024-07-02
      context: |
        The retail client disputed a batch of printed panels,
        claiming colour drift. Evidence was inconclusive.
      chosen_path: "Offered a partial reprint on the worst panel."
      rejected_alternatives:
        - path: "Reprint everything free"
          reason: "Not justified by the available evidence."
      outcome: |
        Client accepted the partial remedy and paid the invoice.
      chosen_path_score: 0.8
"""


@pytest.fixture
def disputes_yaml(tmp_path: Path) -> Path:
    path = tmp_path / 'disputes.yml'
    path.write_text(_FIXTURE_YAML, encoding='utf-8')
    return path


# ── Parser tests ───────────────────────────────────────────────────────


def test_source_yields_all_phases(disputes_yaml):
    from scripts.backfill.sources.disputes import DisputesSource
    source = DisputesSource(yaml_path=disputes_yaml)
    records = list(source.iter_records())
    # 2 phases in the first case + 1 phase in the second case
    assert len(records) == 3
    # All dispute source_type
    assert {r.source_type for r in records} == {'dispute'}
    # Signal strength is fixed
    assert all(r.signal_strength == 0.95 for r in records)
    # Deterministic ids use the case_id + phase name
    ids = {r.deterministic_id for r in records}
    assert 'backfill_dispute_evri-example-2024_initial_response' in ids
    assert 'backfill_dispute_evri-example-2024_escalation' in ids
    assert 'backfill_dispute_retail-colour-drift-2024_initial_complaint' in ids


def test_case_level_lesson_attaches_to_last_phase_only(disputes_yaml):
    from scripts.backfill.sources.disputes import DisputesSource
    records = list(DisputesSource(yaml_path=disputes_yaml).iter_records())
    by_id = {r.deterministic_id: r for r in records}

    # First case has a case-level lesson. Only the LAST phase gets it.
    first_phase = by_id['backfill_dispute_evri-example-2024_initial_response']
    last_phase = by_id['backfill_dispute_evri-example-2024_escalation']
    assert first_phase.verbatim_lesson is None
    assert last_phase.verbatim_lesson is not None
    assert 'first settlement offer' in last_phase.verbatim_lesson
    assert last_phase.verbatim_lesson_model == 'toby_verbatim'

    # Second case has no case-level lesson — nobody gets verbatim.
    retail_phase = by_id['backfill_dispute_retail-colour-drift-2024_initial_complaint']
    assert retail_phase.verbatim_lesson is None


def test_context_becomes_summary(disputes_yaml):
    """The YAML context is treated as the canonical summary — no Haiku rewrite."""
    from scripts.backfill.sources.disputes import DisputesSource
    records = list(DisputesSource(yaml_path=disputes_yaml).iter_records())
    assert all(r.context_summary is not None for r in records)
    assert all(r.raw_text is None for r in records)
    # Tags stay None so the pipeline calls Haiku for tagging.
    assert all(r.archetype_tags is None for r in records)


def test_rejected_alternatives_parsed(disputes_yaml):
    from scripts.backfill.sources.disputes import DisputesSource
    records = list(DisputesSource(yaml_path=disputes_yaml).iter_records())
    first = next(
        r for r in records
        if r.deterministic_id == 'backfill_dispute_evri-example-2024_initial_response'
    )
    assert first.rejected_paths is not None
    assert len(first.rejected_paths) == 2
    assert first.rejected_paths[0]['path'].startswith('Accept GBP300')
    assert 'precedent' in first.rejected_paths[0]['reason'].lower()


def test_outcome_and_metrics(disputes_yaml):
    from scripts.backfill.sources.disputes import DisputesSource
    records = list(DisputesSource(yaml_path=disputes_yaml).iter_records())
    first = next(
        r for r in records
        if r.deterministic_id == 'backfill_dispute_evri-example-2024_initial_response'
    )
    assert first.outcome is not None
    assert 'GBP350' in first.outcome.actual_result
    assert first.outcome.chosen_path_score == 0.7
    assert first.outcome.metrics == {'settlement_gbp': 350, 'days_to_resolve': 45}


def test_case_id_links_phases(disputes_yaml):
    from scripts.backfill.sources.disputes import DisputesSource
    records = list(DisputesSource(yaml_path=disputes_yaml).iter_records())
    case_groups: dict[str, list] = {}
    for r in records:
        case_groups.setdefault(r.case_id, []).append(r)
    assert len(case_groups['evri-example-2024']) == 2
    assert len(case_groups['retail-colour-drift-2024']) == 1


def test_raw_source_ref_carries_yaml_path(disputes_yaml):
    from scripts.backfill.sources.disputes import DisputesSource
    records = list(DisputesSource(yaml_path=disputes_yaml).iter_records())
    first = records[0]
    assert first.raw_source_ref['yaml_path'] == str(disputes_yaml)
    assert first.raw_source_ref['case_id'] == 'evri-example-2024'
    assert first.raw_source_ref['phase'] in {'initial_response', 'escalation'}
    assert first.raw_source_ref['parties'] == ['NBNE', 'Evri', 'ExampleClient']
    assert first.raw_source_ref['initial_claim_gbp'] == 1705
    assert first.raw_source_ref['final_settlement_gbp'] == 350


# ── Error cases ────────────────────────────────────────────────────────


def test_missing_file_raises(tmp_path):
    from scripts.backfill.sources.disputes import DisputesSource, DisputeYamlError
    with pytest.raises(DisputeYamlError, match='not found'):
        DisputesSource(yaml_path=tmp_path / 'does-not-exist.yml')


def test_empty_file_yields_nothing(tmp_path):
    from scripts.backfill.sources.disputes import DisputesSource
    path = tmp_path / 'disputes.yml'
    path.write_text('', encoding='utf-8')
    assert list(DisputesSource(yaml_path=path).iter_records()) == []


def test_missing_case_id_raises(tmp_path):
    from scripts.backfill.sources.disputes import DisputesSource, DisputeYamlError
    path = tmp_path / 'disputes.yml'
    path.write_text(
        '- phases:\n'
        '    - phase: x\n'
        '      decided_at: 2024-01-01\n'
        '      context: y\n'
        '      chosen_path: z\n',
        encoding='utf-8',
    )
    with pytest.raises(DisputeYamlError, match='case_id'):
        list(DisputesSource(yaml_path=path).iter_records())


def test_missing_chosen_path_raises(tmp_path):
    from scripts.backfill.sources.disputes import DisputesSource, DisputeYamlError
    path = tmp_path / 'disputes.yml'
    path.write_text(
        '- case_id: x\n'
        '  phases:\n'
        '    - phase: y\n'
        '      decided_at: 2024-01-01\n'
        '      context: z\n',
        encoding='utf-8',
    )
    with pytest.raises(DisputeYamlError, match='chosen_path'):
        list(DisputesSource(yaml_path=path).iter_records())


def test_bad_date_string_raises(tmp_path):
    from scripts.backfill.sources.disputes import DisputesSource, DisputeYamlError
    path = tmp_path / 'disputes.yml'
    path.write_text(
        '- case_id: x\n'
        '  phases:\n'
        '    - phase: y\n'
        '      decided_at: "not a date"\n'
        '      context: z\n'
        '      chosen_path: w\n',
        encoding='utf-8',
    )
    with pytest.raises(DisputeYamlError, match='not a valid ISO'):
        list(DisputesSource(yaml_path=path).iter_records())


def test_preflight_flags_missing_disputes_yml(tmp_path):
    """Preflight points at the missing file, not at parser errors."""
    from scripts.backfill.run import preflight
    failures = preflight(
        sources=['disputes'],
        data_dir=tmp_path,
        commit_mode=False,
    )
    assert any('disputes.yml' in f and 'Toby must write' in f for f in failures)


def test_preflight_accepts_built_disputes(tmp_path):
    """Once disputes.yml exists, preflight stops complaining about 'not built'."""
    from scripts.backfill.run import preflight
    (tmp_path / 'disputes.yml').write_text(_FIXTURE_YAML, encoding='utf-8')
    failures = preflight(
        sources=['disputes'],
        data_dir=tmp_path,
        commit_mode=False,
    )
    # The 'not yet implemented' message must be absent.
    assert not any('not yet implemented' in f for f in failures)
