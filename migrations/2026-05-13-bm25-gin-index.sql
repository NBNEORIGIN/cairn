-- Phase 4 of the inbox learning loop (2026-05-13).
--
-- Persistent BM25 / lexical retrieval via a GIN index on the chunk
-- text. The hybrid retriever previously held a Python BM25Okapi
-- structure in memory per worker, rebuilt from a full table scan
-- every CACHE_TTL_SECONDS. That:
--
--   * cost a few seconds on cold start as 100k+ rows were tokenized
--   * pinned chunk text in RAM per worker
--   * went stale between rebuilds — newly-indexed emails couldn't
--     be retrieved lexically until the next refresh
--
-- With this index in place, Postgres scores ts_rank_cd over the full
-- corpus on demand. No cache, no staleness, no RAM cost. New rows
-- become searchable as soon as they're committed.
--
-- The retriever falls back to the in-memory path if the index is
-- missing (e.g. on a fresh deploy before this migration has run), so
-- this is safe to apply with zero coordination on the application side.
--
-- Idempotent: re-running is a no-op.

CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- enables similarity() too

-- Functional GIN over the English text-search config. Functional
-- (not a generated column) so we don't have to ALTER the table
-- shape — keeps the migration small and reversible.
CREATE INDEX IF NOT EXISTS claw_code_chunks_chunk_content_tsv_idx
    ON claw_code_chunks
    USING GIN (to_tsvector('english', COALESCE(chunk_content, '')));

-- Secondary index on (project_id, chunk_type) so the BM25 query can
-- pre-filter cheaply before applying the tsvector predicate. The
-- existing index on project_id alone isn't quite right because most
-- queries also constrain on chunk_type (email/wiki/code etc.).
CREATE INDEX IF NOT EXISTS claw_code_chunks_project_chunktype_idx
    ON claw_code_chunks (project_id, chunk_type);

-- Trigram index on file_path so rare exact-string matches (project
-- IDs, message-ids embedded in file paths) hit faster than a LIKE
-- scan. Cheap to maintain at our volume.
CREATE INDEX IF NOT EXISTS claw_code_chunks_file_path_trgm_idx
    ON claw_code_chunks
    USING GIN (file_path gin_trgm_ops);

-- Self-documenting comment so anyone running \d+ on the table sees
-- why these exist.
COMMENT ON INDEX claw_code_chunks_chunk_content_tsv_idx IS
    'BM25/FTS persistence — Phase 4 inbox learning loop. See '
    'migrations/2026-05-13-bm25-gin-index.sql and core/memory/retriever.py.';
