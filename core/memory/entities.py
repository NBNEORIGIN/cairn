"""Entity extraction for the crosslink graph (Brief 3 Phase A).

Regex + canonical-list matching against the Toby-curated files in
config/. No spaCy — generic NER is a poor fit for NBNE's domain and
this pattern runs at <1ms per memory.

Wired into _embed_memory_to_pgvector (api/main.py) so every memory
write extracts entities, upserts nodes, links memory↔entity, and
reinforces co-occurrence edges.

See docs/CROSSLINK_GRAPH.md for the mechanism and tuning notes.
"""
from __future__ import annotations

import itertools
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TAXONOMY_PATH = Path(
    os.getenv('DEEK_ENTITY_TAXONOMY',
              str(_REPO_ROOT / 'config' / 'entity_taxonomy.yaml'))
)

# Outcome → signal contribution. Matches the salience outcome table
# but maps into [-1, +1] for graph edge weighting. Unknown outcomes
# score 0 (neutral).
_OUTCOME_SIGNAL: dict[str, float] = {
    'fail': -1.0, 'failed': -1.0, 'blocked': -0.8,
    'rollback': -0.8,
    'deferred': -0.2, 'partial': 0.0,
    'win': 0.8, 'success': 1.0, 'committed': 0.6,
}


# ── Data types ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EntityRef:
    """One extracted entity mention.

    Canonical form is lower-case + whitespace-collapsed — the DB
    unique key is (type, canonical_name).
    """
    type: str
    canonical_name: str
    display_name: str


@dataclass
class Taxonomy:
    entity_types: list[dict] = field(default_factory=list)
    stop_entities: set[str] = field(default_factory=set)


# ── Canonicalisation ──────────────────────────────────────────────────

_WS_RE = re.compile(r'\s+')


def canonicalise(text: str) -> str:
    """Lower-case + strip + collapse whitespace. Idempotent."""
    if not text:
        return ''
    return _WS_RE.sub(' ', text.strip()).lower()


# ── Taxonomy loading ──────────────────────────────────────────────────

_taxonomy_cache: Taxonomy | None = None
_lock = threading.Lock()


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as exc:
        logger.warning('[entities] yaml load %s failed: %s', path, exc)
        return {}


def _load_canonical_list(list_path: str) -> list[tuple[str, str, list[str]]]:
    """Return list of (canonical, display, aliases) from a YAML file.

    Structure expected:
        <top_key>:
          - canonical: Display Name
            aliases: [alt1, alt2]
    """
    abs_path = _REPO_ROOT / list_path
    data = _load_yaml(abs_path)
    if not data:
        return []
    # find the single top-level list key
    for key, entries in data.items():
        if isinstance(entries, list):
            out = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                disp = str(e.get('canonical') or '').strip()
                if not disp:
                    continue
                aliases = [str(a).strip() for a in (e.get('aliases') or []) if a]
                out.append((canonicalise(disp), disp, aliases))
            return out
    return []


def _load_deek_modules() -> list[tuple[str, str, list[str]]]:
    """Get module names from DEEK_MODULES.yaml via the identity assembler."""
    try:
        from core.identity import assembler
        out = []
        for m in assembler.get_modules():
            out.append((canonicalise(m.name), m.display_name, [m.display_name]))
        return out
    except Exception as exc:
        logger.debug('[entities] deek modules load failed: %s', exc)
        return []


def load_taxonomy(force: bool = False) -> Taxonomy:
    """Load the taxonomy once, cache the result."""
    global _taxonomy_cache
    with _lock:
        if _taxonomy_cache is not None and not force:
            return _taxonomy_cache
        data = _load_yaml(_TAXONOMY_PATH)
        taxonomy = Taxonomy(
            entity_types=list(data.get('entity_types') or []),
            stop_entities=set(
                canonicalise(s) for s in (data.get('stop_entities') or [])
            ),
        )
        _taxonomy_cache = taxonomy
        return taxonomy


# ── Per-type matchers ─────────────────────────────────────────────────

def _regex_matches(text: str, pattern: str) -> list[str]:
    """Return the full matched strings (group 0) for each match."""
    if not text or not pattern:
        return []
    try:
        return [m.group(0) for m in re.finditer(pattern, text)]
    except re.error as exc:
        logger.warning('[entities] bad regex %r: %s', pattern, exc)
        return []


def _canonical_list_matches(
    text: str, entries: list[tuple[str, str, list[str]]]
) -> list[tuple[str, str]]:
    """Return (canonical, display) pairs for any matched names/aliases.

    Case-insensitive substring match with word-boundary guard — prevents
    "ami" matching inside "family". Short names (<3 chars) are skipped
    to avoid noise.
    """
    if not text or not entries:
        return []
    lower = text.lower()
    hits: list[tuple[str, str]] = []
    for canonical, display, aliases in entries:
        candidates = [display] + list(aliases)
        for cand in candidates:
            if len(cand) < 3:
                continue
            pat = r'\b' + re.escape(cand.lower()) + r'\b'
            if re.search(pat, lower):
                hits.append((canonical, display))
                break  # match by any alias counts as one hit
    return hits


# ── Extractor ─────────────────────────────────────────────────────────

def extract_entities(
    memory_text: str,
    metadata: dict | None = None,
    taxonomy: Taxonomy | None = None,
) -> list[EntityRef]:
    """Extract entity references from a memory text.

    Precedence: earlier types in the taxonomy claim their spans first.
    Stop-entities are dropped. Duplicates (same type + canonical_name)
    collapse to one.

    Args:
        memory_text: the full text of the memory (task + decision + etc).
        metadata: optional — currently unused, kept for future signals.
        taxonomy: optional override for tests; defaults to loaded YAML.
    """
    if not memory_text:
        return []
    tax = taxonomy or load_taxonomy()
    seen: set[tuple[str, str]] = set()
    refs: list[EntityRef] = []

    for spec in tax.entity_types:
        t_name = str(spec.get('name') or '').strip()
        if not t_name:
            continue
        source = str(spec.get('source') or '').strip()

        matches: list[tuple[str, str]] = []  # (canonical, display)
        if source == 'regex':
            for m in _regex_matches(memory_text, str(spec.get('pattern') or '')):
                matches.append((canonicalise(m), m))
        elif source == 'canonical_list':
            entries = _load_canonical_list(str(spec.get('list_path') or ''))
            matches.extend(_canonical_list_matches(memory_text, entries))
        elif source == 'deek_modules_yaml':
            entries = _load_deek_modules()
            matches.extend(_canonical_list_matches(memory_text, entries))
        else:
            continue

        for canonical, display in matches:
            canonical = canonicalise(canonical)
            if not canonical:
                continue
            if canonical in tax.stop_entities:
                continue
            key = (t_name, canonical)
            if key in seen:
                continue
            seen.add(key)
            refs.append(EntityRef(
                type=t_name, canonical_name=canonical, display_name=display,
            ))
    return refs


# ── Outcome signal from metadata ──────────────────────────────────────

def outcome_signal(metadata: dict | None) -> float:
    if not metadata:
        return 0.0
    outcome = str(metadata.get('outcome') or '').strip().lower()
    return float(_OUTCOME_SIGNAL.get(outcome, 0.0))


# ── DB write path ─────────────────────────────────────────────────────

def _uuid() -> str:
    return str(uuid.uuid4())


def upsert_entities_and_edges(
    memory_id: int,
    refs: Iterable[EntityRef],
    outcome: float,
    conn,
) -> dict:
    """Apply entity writes for one memory.

    Given an already-open psycopg2 connection (so we stay inside the
    caller's transaction), upsert each entity node, link memory→entity,
    and reinforce co-occurrence edges. Returns a summary dict.

    Edge convention: (source_id < target_id) lexicographic so we store
    each undirected pair once. Aligns with the CHECK constraint in
    migrations/postgres/0002_crosslink_graph.sql.

    outcome_signal is blended as a running mean:
        new_mean = old_mean + (x - old_mean) / new_count
    """
    refs_list = list(refs)
    summary = {'nodes_upserted': 0, 'edges_upserted': 0}
    if not refs_list:
        return summary
    with conn.cursor() as cur:
        # Upsert each node; fetch back its id.
        node_ids: list[str] = []
        for r in refs_list:
            cur.execute(
                """
                INSERT INTO entity_nodes
                    (id, type, canonical_name, display_name, aliases,
                     first_seen, last_seen, mention_count)
                VALUES (%s, %s, %s, %s, '{}'::text[], NOW(), NOW(), 1)
                ON CONFLICT (type, canonical_name) DO UPDATE SET
                    last_seen = NOW(),
                    mention_count = entity_nodes.mention_count + 1,
                    display_name = COALESCE(
                        NULLIF(entity_nodes.display_name, ''),
                        EXCLUDED.display_name
                    )
                RETURNING id::text
                """,
                (_uuid(), r.type, r.canonical_name, r.display_name),
            )
            (node_id,) = cur.fetchone()
            node_ids.append(node_id)
            summary['nodes_upserted'] += 1

            # Link memory to this entity (skip if already linked — ON CONFLICT).
            cur.execute(
                """
                INSERT INTO memory_entities (memory_id, entity_id)
                VALUES (%s, %s::uuid)
                ON CONFLICT DO NOTHING
                """,
                (memory_id, node_id),
            )

        # Every pair of co-occurring entities in this memory → edge.
        for a, b in itertools.combinations(node_ids, 2):
            src, tgt = (a, b) if a < b else (b, a)
            cur.execute(
                """
                INSERT INTO entity_edges
                    (source_id, target_id, weight, co_occurrence_count,
                     outcome_signal, last_reinforced)
                VALUES (%s::uuid, %s::uuid, 1.0, 1, %s, NOW())
                ON CONFLICT (source_id, target_id) DO UPDATE SET
                    co_occurrence_count = entity_edges.co_occurrence_count + 1,
                    outcome_signal = entity_edges.outcome_signal
                        + (%s - entity_edges.outcome_signal)
                          / (entity_edges.co_occurrence_count + 1),
                    weight = LEAST(
                        10.0,
                        entity_edges.weight
                            + 1.0 / (entity_edges.co_occurrence_count + 1)
                    ),
                    last_reinforced = NOW()
                """,
                (src, tgt, outcome, outcome),
            )
            summary['edges_upserted'] += 1
    return summary


__all__ = [
    'EntityRef', 'Taxonomy',
    'canonicalise', 'load_taxonomy', 'extract_entities',
    'outcome_signal', 'upsert_entities_and_edges',
]
