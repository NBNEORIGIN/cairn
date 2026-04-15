"""Cairn cross-module delegation package.

Surface for external CC sessions (Beacon, Phloe, Render, CRM, etc.) to delegate
generation / review / extraction / classification work to junior tiers
(Grok 4 Fast, Claude Haiku 4.5) via OpenRouter, with call-level cost logging.

Distinct from ``core/models/router.py`` — that file routes Cairn's internal
agent loop across local/hosted providers. This package handles cross-module
delegation only. Do not conflate.
"""
