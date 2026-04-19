"""Unit tests for core.memory.consolidation (Brief 2 Phase B).

Covers the DB-independent surface: clustering, Ollama response parsing,
and the schema retrieval heuristics. DB + live-Ollama integration is
exercised in the post-deploy smoke run, not here — we keep unit tests
hermetic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.memory.consolidation import (
    CandidateMemory, _cosine, cluster_candidates,
    call_ollama_consolidation,
)


def _mk_candidate(cid: int, embedding: list[float]) -> CandidateMemory:
    return CandidateMemory(
        chunk_id=cid,
        project_id='deek',
        file_path=f'memory/deek/{cid}',
        chunk_content=f'Memory {cid}',
        salience=5.0,
        last_accessed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        embedding=embedding,
    )


class TestCosine:
    def test_identical_ones(self):
        assert _cosine([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_length_mismatch_zero(self):
        assert _cosine([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vectors(self):
        assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestClustering:
    def test_empty(self):
        assert cluster_candidates([]) == []

    def test_singleton_dropped(self):
        # A single candidate can't form a cluster of >= 3
        c = _mk_candidate(1, [1.0, 0.0, 0.0])
        assert cluster_candidates([c]) == []

    def test_two_similar_dropped(self):
        # A pair below MIN_CLUSTER_SIZE is also dropped
        a = _mk_candidate(1, [1.0, 0.0, 0.0])
        b = _mk_candidate(2, [0.99, 0.01, 0.0])
        assert cluster_candidates([a, b]) == []

    def test_three_similar_form_cluster(self):
        a = _mk_candidate(1, [1.0, 0.0, 0.0])
        b = _mk_candidate(2, [0.95, 0.05, 0.0])
        c = _mk_candidate(3, [0.9, 0.1, 0.0])
        clusters = cluster_candidates([a, b, c])
        assert len(clusters) == 1
        assert {m.chunk_id for m in clusters[0]} == {1, 2, 3}

    def test_two_disjoint_clusters(self):
        # Three similar in group A, three in group B, orthogonal
        a1 = _mk_candidate(1, [1.0, 0.0, 0.0])
        a2 = _mk_candidate(2, [0.97, 0.02, 0.0])
        a3 = _mk_candidate(3, [0.92, 0.08, 0.0])
        b1 = _mk_candidate(4, [0.0, 1.0, 0.0])
        b2 = _mk_candidate(5, [0.0, 0.95, 0.0])
        b3 = _mk_candidate(6, [0.0, 0.9, 0.1])
        clusters = cluster_candidates([a1, a2, a3, b1, b2, b3])
        assert len(clusters) == 2
        cluster_id_sets = sorted(
            sorted(m.chunk_id for m in cl) for cl in clusters
        )
        assert cluster_id_sets == [[1, 2, 3], [4, 5, 6]]

    def test_mixed_cluster_plus_outliers(self):
        # 3 similar + 2 orthogonal pairs → one 3-cluster, outliers dropped
        a1 = _mk_candidate(1, [1.0, 0.0, 0.0])
        a2 = _mk_candidate(2, [0.95, 0.05, 0.0])
        a3 = _mk_candidate(3, [0.92, 0.08, 0.0])
        o1 = _mk_candidate(4, [0.0, 1.0, 0.0])  # alone
        o2 = _mk_candidate(5, [0.0, 0.0, 1.0])  # alone
        clusters = cluster_candidates([a1, a2, a3, o1, o2])
        assert len(clusters) == 1
        assert {m.chunk_id for m in clusters[0]} == {1, 2, 3}


# ── Ollama response parsing (mock httpx.Client.post) ──────────────────

class _FakeResp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *args, **kwargs):
        return self._resp


class TestCallOllama:
    def _cluster(self) -> list[CandidateMemory]:
        return [
            _mk_candidate(10, [1.0, 0.0]),
            _mk_candidate(11, [0.95, 0.05]),
            _mk_candidate(12, [0.92, 0.08]),
        ]

    def test_none_response(self, monkeypatch):
        resp = _FakeResp(200, {'message': {'content': 'NONE'}})
        import httpx
        monkeypatch.setattr(httpx, 'Client', lambda *a, **k: _FakeClient(resp))
        assert call_ollama_consolidation(self._cluster(), 'http://x', 'm') is None

    def test_non_200(self, monkeypatch):
        resp = _FakeResp(500, {'error': 'boom'})
        import httpx
        monkeypatch.setattr(httpx, 'Client', lambda *a, **k: _FakeClient(resp))
        assert call_ollama_consolidation(self._cluster(), 'http://x', 'm') is None

    def test_malformed_json(self, monkeypatch):
        resp = _FakeResp(200, {'message': {'content': 'this is not json'}})
        import httpx
        monkeypatch.setattr(httpx, 'Client', lambda *a, **k: _FakeClient(resp))
        assert call_ollama_consolidation(self._cluster(), 'http://x', 'm') is None

    def test_happy_path(self, monkeypatch):
        body = {
            'message': {'content':
                '{"statement": "NBNE favours quick iteration.", '
                '"source_memory_ids": [10, 11, 12], "confidence": 0.85}'
            }
        }
        resp = _FakeResp(200, body)
        import httpx
        monkeypatch.setattr(httpx, 'Client', lambda *a, **k: _FakeClient(resp))
        out = call_ollama_consolidation(self._cluster(), 'http://x', 'm')
        assert out is not None
        assert out.statement == 'NBNE favours quick iteration.'
        assert out.source_memory_ids == [10, 11, 12]
        assert out.confidence == 0.85

    def test_grounding_rejected(self, monkeypatch):
        # IDs not in the input cluster must be stripped; if fewer than
        # MIN_CLUSTER_SIZE remain, the candidate is rejected.
        body = {
            'message': {'content':
                '{"statement": "Hallucinated", '
                '"source_memory_ids": [999, 998, 997], "confidence": 0.9}'
            }
        }
        resp = _FakeResp(200, body)
        import httpx
        monkeypatch.setattr(httpx, 'Client', lambda *a, **k: _FakeClient(resp))
        assert call_ollama_consolidation(self._cluster(), 'http://x', 'm') is None

    def test_prose_wrapped_json(self, monkeypatch):
        # Models often add commentary around the JSON. Parser should
        # find the object by brace detection.
        body = {
            'message': {'content':
                'Sure, here is the pattern I see:\n\n'
                '{"statement": "Batch inference saves cost.", '
                '"source_memory_ids": [10, 11, 12], "confidence": 0.72}\n\n'
                'Hope that helps!'
            }
        }
        resp = _FakeResp(200, body)
        import httpx
        monkeypatch.setattr(httpx, 'Client', lambda *a, **k: _FakeClient(resp))
        out = call_ollama_consolidation(self._cluster(), 'http://x', 'm')
        assert out is not None
        assert 'Batch inference' in out.statement
