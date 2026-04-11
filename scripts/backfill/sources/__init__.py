"""
Backfill source adapters.

Each adapter translates a domain-specific history (disputes YAML,
Manufacture M-numbers, Xero P&L, etc.) into a stream of
``RawHistoricalRecord`` objects that the shared pipeline can write
into ``cairn_intel.decisions``.

See ``sources/base.py`` for the protocol every source must implement.
Phase 2 ships a single synthetic source (``sources/synthetic.py``)
that yields pre-tagged fixture records to exercise the pipeline
without any real data or LLM calls.
"""
