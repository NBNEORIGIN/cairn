"""Unit tests for core.memory.schema_retrieval (Brief 2 Phase B)."""
from __future__ import annotations

from core.memory.schema_retrieval import is_strategic_query


class TestStrategicHeuristic:
    def test_empty(self):
        assert is_strategic_query('') is False

    def test_keyword_architecture(self):
        assert is_strategic_query('what architecture should we use?')

    def test_keyword_principle(self):
        assert is_strategic_query('recurring principle we follow')

    def test_keyword_should_we(self):
        assert is_strategic_query('should we rebuild the voice endpoint?')

    def test_short_factual_false(self):
        assert is_strategic_query('what time is it?') is False
        assert is_strategic_query('how many orders today') is False

    def test_long_query_true_even_without_keywords(self):
        # Long queries often are strategic; trip the token threshold.
        q = ' '.join(['word'] * 25)
        assert is_strategic_query(q) is True

    def test_case_insensitive(self):
        assert is_strategic_query('ARCHITECTURE review needed')

    def test_mid_keyword(self):
        # "pattern" in the middle of a sentence still counts
        assert is_strategic_query('I noticed a pattern last week')


class TestRetrieveSchemas:
    def test_no_embedding_fn(self):
        from core.memory.schema_retrieval import retrieve_schemas
        assert retrieve_schemas('test', None) == []

    def test_empty_query(self):
        from core.memory.schema_retrieval import retrieve_schemas
        assert retrieve_schemas('', lambda t: [0.0, 0.0]) == []

    def test_no_db_url(self, monkeypatch):
        monkeypatch.delenv('DATABASE_URL', raising=False)
        from core.memory.schema_retrieval import retrieve_schemas
        assert retrieve_schemas('something', lambda t: [1.0]) == []


class TestReinforceSchemasAsync:
    def test_empty_noop(self):
        from core.memory.schema_retrieval import reinforce_schemas_async
        reinforce_schemas_async([])

    def test_graceful_no_db(self, monkeypatch):
        monkeypatch.delenv('DATABASE_URL', raising=False)
        from core.memory.schema_retrieval import _reinforce_schemas_sync
        _reinforce_schemas_sync(['abc-123'])
