"""
Tests for ``scripts.backfill.sources.principles``.

Phase 4 ships the wiki-on-disk branch only. The tagger's
``_get_client`` is replaced with a MagicMock that returns a fixed
list of sentences, so these tests exercise:

- Iteration over a tmp wiki directory
- Haiku extraction call dispatch + budget consumption
- Sentence deduplication via cosine similarity ≥ 0.92
- Record shape (signal_strength, verbatim_lesson, raw_source_ref)
- Process-y sentence filtering
- max_files cap
- 'NONE' response handling
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Deterministic fake embedder shared with the other intel tests.
def _fake_embed(text: str) -> list[float]:
    import hashlib
    vec = [0.0] * 768
    for word in text.lower().split():
        digest = hashlib.md5(word.encode('utf-8')).digest()
        for i in range(0, 16, 2):
            idx = (digest[i] * 256 + digest[i + 1]) % 768
            vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _make_mock_tagger(response_lines: list[str]):
    """Build an ArchetypeTagger whose client returns the given lines."""
    from scripts.backfill.llm_budget import LLMBudget
    from scripts.backfill.archetype_tagger import ArchetypeTagger

    budget = LLMBudget(max_sonnet=5, max_opus=5, max_bulk=100)
    tagger = ArchetypeTagger(budget=budget, api_key='test-key')

    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(type='text', text='\n'.join(response_lines))]
    client.messages.create.return_value = resp
    tagger._client = client
    return tagger, budget, client


@pytest.fixture
def wiki_tmp(tmp_path: Path) -> Path:
    wiki = tmp_path / 'wiki'
    wiki.mkdir()
    (wiki / 'article_1.md').write_text(
        'Sometimes we handle pricing by anchoring on the middle option '
        'and designing it to land at the client budget ceiling. The '
        'rest is decoration.',
        encoding='utf-8',
    )
    (wiki / 'article_2.md').write_text(
        'Never undercut your own Amazon listings on Etsy because it '
        'trains buyers to wait for the cheaper platform.',
        encoding='utf-8',
    )
    # Tiny file — should be skipped.
    (wiki / 'tiny.md').write_text('Nothing useful.', encoding='utf-8')
    return wiki


# ── Core tests ─────────────────────────────────────────────────────────


def test_iterates_and_yields_records(wiki_tmp):
    from scripts.backfill.sources.principles import PrinciplesSource

    tagger, budget, client = _make_mock_tagger([
        'Never undercut your own Amazon listings on Etsy, the platforms '
        'serve different buyer segments.',
        'When clients have a firm budget, lead with the middle of three '
        'options at exactly their ceiling.',
    ])
    source = PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed)
    records = list(source.iter_records())
    # 3 md files -> 2 substantive, 1 short (skipped). Both substantive
    # files return the same two sentences from the mock, then dedupe
    # kicks in on the second file so we end with the first file's 2.
    assert len(records) == 2
    assert all(r.source_type == 'principle' for r in records)
    assert all(r.signal_strength == 1.0 for r in records)
    # Budget used: 2 Haiku calls (one per non-tiny file).
    assert budget.bulk_used == 2


def test_verbatim_lesson_equals_sentence(wiki_tmp):
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, _, _ = _make_mock_tagger([
        'Never accept the first settlement offer from a courier.',
    ])
    records = list(
        PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed).iter_records()
    )
    assert records
    first = records[0]
    assert first.chosen_path == first.verbatim_lesson
    assert first.verbatim_lesson_model == 'toby_verbatim'
    assert first.outcome is not None
    # The context summary is the same sentence — no Haiku summarise call.
    assert first.context_summary == first.chosen_path


def test_dedupe_rejects_near_duplicates(wiki_tmp):
    """Dedupe runs across files and within a file."""
    from scripts.backfill.sources.principles import PrinciplesSource
    # Two identical sentences — the first is kept, the second is a
    # perfect cosine match and rejected. Across 2 files (4 total
    # extractions) we should still end up with exactly 1 record.
    tagger, _, _ = _make_mock_tagger([
        'Never undercut your own Amazon listings on Etsy in any circumstance.',
        'Never undercut your own Amazon listings on Etsy in any circumstance.',
    ])
    records = list(
        PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed).iter_records()
    )
    assert len(records) == 1


def test_none_response_yields_no_records(wiki_tmp):
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, budget, _ = _make_mock_tagger(['NONE'])
    records = list(
        PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed).iter_records()
    )
    assert records == []
    # We still spent Haiku calls on each substantive file.
    assert budget.bulk_used == 2


def test_max_files_cap(wiki_tmp):
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, budget, _ = _make_mock_tagger(['Some principle sentence here.'])
    source = PrinciplesSource(
        wiki_dir=wiki_tmp,
        tagger=tagger,
        embed_fn=_fake_embed,
        max_files=1,
    )
    list(source.iter_records())
    # Only one file processed — exactly one Haiku call.
    assert budget.bulk_used == 1


def test_short_sentences_are_filtered(wiki_tmp):
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, _, _ = _make_mock_tagger(['Too short.'])  # len < min_length default 25
    records = list(
        PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed).iter_records()
    )
    assert records == []


def test_process_y_sentences_are_filtered(wiki_tmp):
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, _, _ = _make_mock_tagger([
        'Click the big red button to submit the form for production.',
        'Hold your price when the buyer is negotiating aggressively on terms.',
    ])
    records = list(
        PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed).iter_records()
    )
    # The "Click the big red button" line is a process instruction → filtered.
    # The "Hold your price" line survives.
    assert len(records) == 1
    assert records[0].chosen_path.startswith('Hold your price')


def test_missing_wiki_dir_is_safe(tmp_path):
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, _, _ = _make_mock_tagger(['x'])
    source = PrinciplesSource(
        wiki_dir=tmp_path / 'does-not-exist',
        tagger=tagger,
        embed_fn=_fake_embed,
    )
    assert list(source.iter_records()) == []


def test_deterministic_id_is_hash_of_sentence(wiki_tmp):
    import hashlib
    from scripts.backfill.sources.principles import PrinciplesSource

    sentence = 'Hold your price when the buyer is negotiating aggressively on terms.'
    tagger, _, _ = _make_mock_tagger([sentence])
    records = list(
        PrinciplesSource(wiki_dir=wiki_tmp, tagger=tagger, embed_fn=_fake_embed).iter_records()
    )
    assert records
    expected_hash = hashlib.sha256(sentence.encode('utf-8')).hexdigest()[:12]
    assert records[0].deterministic_id == f'backfill_principle_{expected_hash}'


def test_embedding_provider_that_returns_none_skips_records(wiki_tmp):
    """If the embedder returns None (no provider), dedupe can't run → skip."""
    from scripts.backfill.sources.principles import PrinciplesSource
    tagger, _, _ = _make_mock_tagger(['A perfectly fine principle sentence here.'])
    records = list(
        PrinciplesSource(
            wiki_dir=wiki_tmp,
            tagger=tagger,
            embed_fn=lambda text: None,
        ).iter_records()
    )
    assert records == []


# ── Module-level helpers ───────────────────────────────────────────────


def test_cosine_and_is_duplicate():
    from scripts.backfill.sources.principles import _cosine, _is_duplicate

    a = _fake_embed('aggressive pricing negotiation')
    b = _fake_embed('aggressive pricing negotiation')  # identical
    c = _fake_embed('routine production scheduling')

    assert _cosine(a, b) == pytest.approx(1.0)
    assert _cosine(a, c) < 0.95

    kept = [(a, 'prior')]
    assert _is_duplicate(b, kept, threshold=0.92) is True
    assert _is_duplicate(c, kept, threshold=0.92) is False
