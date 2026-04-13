"""
Task Classifier — complexity-based tier selection matching the CLAUDE.md matrix.

CLAUDE.md defines four tiers:

  Low      — Single file, mechanical edit, boilerplate, no design decision
  Medium   — Multi-file, bug diagnosis, moderate feature, known pattern
  High     — Architecture, cross-project, new pattern, significant risk
  Critical — Irreversible, security, data migration, payment flow

These map to inference tiers:

  Low      → Tier 1 LOCAL    (Qwen/Ollama — free)
  Medium   → Tier 2 DEEPSEEK (DeepSeek V3 — cheap)
  High     → Tier 3 CLAUDE   (Claude Sonnet)
  Critical → Tier 4 OPUS     (Claude Opus + confirm)

Two secondary axes inform the decision when the primary signal is ambiguous:

  Domain breadth — how many distinct knowledge domains the task touches
  Coupling       — whether sub-steps can be verified independently
"""
from dataclasses import dataclass
from enum import IntEnum


class TaskTier(IntEnum):
    LOCAL    = 1
    DEEPSEEK = 2
    CLAUDE   = 3
    OPUS     = 4

    def label(self) -> str:
        return {1: 'Local', 2: 'DeepSeek', 3: 'Sonnet', 4: 'Opus'}[self.value]


@dataclass
class ClassificationResult:
    tier: TaskTier
    rule: str           # machine-readable rule name
    confidence: float   # 0.0–1.0
    explanation: str    # human-readable one-liner


# ── Critical (→ Opus) ─────────────────────────────────────────────────────────
# Irreversible operations, security sensitive, payment, data migration.
# Multi-word phrases are matched as substrings — more precise than single words.
_CRITICAL_PHRASES: frozenset[str] = frozenset({
    # Data / DB
    'data migration', 'migrate data', 'migrate the database', 'prod migration',
    'drop table', 'delete database', 'truncate table',
    'restore backup', 'point-in-time recovery',
    # Payment
    'payment flow', 'payment system', 'stripe live', 'stripe production',
    'billing system', 'invoice system', 'payment gateway',
    # Security
    'security vulnerability', 'security audit', 'security review',
    'encryption key', 'rotate key', 'key rotation',
    'gdpr', 'data breach', 'access control audit',
    # Isolation / multi-tenancy
    'tenant isolation', 'cross-tenant', 'rbac',
})

# Single words that alone indicate Critical — kept narrow to avoid false positives
_CRITICAL_WORDS: frozenset[str] = frozenset({
    'irreversible', 'compliance',
})

# ── High (→ Sonnet) ───────────────────────────────────────────────────────────
# Architecture decisions, cross-system design, significant new patterns,
# root-cause analysis, and tasks requiring sustained multi-step reasoning.
_HIGH_PHRASES: frozenset[str] = frozenset({
    # Architecture / design
    'design decision', 'design the system', 'system design',
    'trade-off', 'tradeoff', 'trade off',
    'how should i structure', 'how should we structure',
    'best way to build', 'best way to design', 'best approach to',
    'best practice', 'best practices',
    # Root cause / deep debugging
    'root cause', 'why is this', 'why does this', 'why isn\'t this',
    'not working and', 'failing because',
    # Cross-system
    'cross-project', 'cross-module', 'across multiple modules',
    'across multiple services', 'across the entire',
    # New patterns
    'new pattern', 'new approach', 'refactor the', 'restructure the',
    'overhaul the', 'rewrite the',
    # Performance / scalability
    'performance review', 'bottleneck analysis', 'scaling strategy',
    'memory leak', 'n+1 query',
})

_HIGH_WORDS: frozenset[str] = frozenset({
    'architecture', 'architect',
    'refactor', 'restructure', 'overhaul',
    'strategic', 'fundamentally',
    'race condition', 'deadlock', 'concurrency',
})

# ── Medium (→ DeepSeek) ───────────────────────────────────────────────────────
# Standard feature work, bug fixes, data analysis, known patterns.
# Most of Gabby's Amazon analytics queries live here.
_MEDIUM_PHRASES: frozenset[str] = frozenset({
    # Feature implementation
    'implement a', 'implement the', 'create a', 'create the',
    'build a', 'build the', 'add a', 'add the',
    'write a function', 'write a script', 'write a test',
    # Debugging (specific — not root cause)
    'fix the bug', 'fix this bug', 'fix the error', 'fix this error',
    'traceback', 'stack trace', 'not returning', 'returns none',
    # Analysis / reporting
    'analyse the', 'analyze the', 'generate a report', 'pull a report',
    'compare the', 'calculate the', 'aggregate the',
    'worst performing', 'best performing', 'zero sales',
    'show me the data', 'give me a breakdown',
    # Multi-file (known pattern)
    'multiple files', 'several files', 'across files',
    'update all', 'rename all',
    # Testing
    'unit test', 'integration test', 'write tests for',
})

_MEDIUM_WORDS: frozenset[str] = frozenset({
    'implement', 'debug', 'diagnose',
    'analyse', 'analyze', 'integrate',
    'report', 'summarise', 'summarize',
    'migrate',   # alone = standard migration, not prod data migration
})

# ── Local / Low (→ Tier 1 when available, else Tier 2) ───────────────────────
# Pure information retrieval, explanation, simple single-file edits.
# No multi-step reasoning required.
_LOCAL_VERBS: frozenset[str] = frozenset({
    'read', 'search', 'list', 'show', 'explain', 'what is', 'what does',
    'how does', 'describe', 'summarize', 'find', 'look up', 'check',
    'tell me', 'show me', 'what are', 'give me', 'fetch',
    'display', 'print', 'output',
})

# ── Phloe ORM: always Opus (tenant safety) ────────────────────────────────────
_PHLOE_ORM_KEYWORDS: frozenset[str] = frozenset({
    'queryset', 'filter', '.objects',
})

# ── Complexity downgrade signals ──────────────────────────────────────────────
# Presence of these alongside High signals suggests the task is smaller than
# the keyword implies ("just rename one function", "quick refactor").
_DOWNGRADE_SIGNALS: frozenset[str] = frozenset({
    'just ', 'quickly ', 'simple ', 'single ', 'one line', 'one function',
    'tiny ', 'small change', 'minor ',
})

# ── Domain breadth: how many of these domains does the prompt touch? ──────────
# 3+ tightly-coupled domains → escalate one tier.
_DOMAIN_MARKERS: list[frozenset[str]] = [
    frozenset({'api', 'endpoint', 'route', 'request', 'response'}),             # API layer
    frozenset({'database', 'db', 'schema', 'migration', 'query', 'postgres'}),  # Data layer
    frozenset({'frontend', 'react', 'next.js', 'component', 'ui', 'html'}),     # Frontend
    frozenset({'auth', 'token', 'jwt', 'oauth', 'permission'}),                 # Auth
    frozenset({'email', 'smtp', 'postmark', 'notification', 'webhook'}),        # Comms
    frozenset({'payment', 'stripe', 'invoice', 'billing'}),                     # Commerce
    frozenset({'deploy', 'docker', 'nginx', 'hetzner', 'server'}),              # Infra
    frozenset({'amazon', 'ebay', 'etsy', 'marketplace', 'listing'}),            # Marketplace
]


def _domain_count(prompt: str) -> int:
    """Count how many distinct technical domains the prompt mentions."""
    words = set(prompt.lower().split())
    return sum(1 for domain in _DOMAIN_MARKERS if domain & words)


def _has_tight_coupling(prompt: str) -> bool:
    """True if multiple domains are tightly coupled (AND / both / integrate)."""
    p = prompt.lower()
    coupling_words = ('and then', ' and ', 'both ', 'integrate', 'together',
                      'at the same time', 'simultaneously', 'end-to-end')
    return any(w in p for w in coupling_words)


def _is_downgraded(prompt: str) -> bool:
    """True if downgrade signals suggest the task is simpler than keywords imply."""
    p = prompt.lower()
    return any(sig in p for sig in _DOWNGRADE_SIGNALS)


def classify(
    prompt: str,
    risk_level: str = 'safe',
    project: str = '',
    context_files: int = 0,
) -> ClassificationResult:
    """
    Classify a prompt into a TaskTier using the CLAUDE.md complexity matrix.

    Evaluation order (first match wins):
      1. Destructive risk_level          → Opus
      2. Critical phrases / words        → Opus
      3. Phloe ORM without tenant        → Opus
      4. High phrases / words            → Sonnet (unless downgraded)
      5. Domain breadth ≥ 3 + coupling   → Sonnet
      6. Medium phrases / words          → DeepSeek
      7. Review risk                     → DeepSeek
      8. Safe + simple read/explain      → Local (Tier 1)
      9. Default                         → DeepSeek
    """
    p = prompt.lower()

    # ── Rule 1: Destructive operations → Opus ────────────────────────────────
    if risk_level == 'destructive':
        return ClassificationResult(
            tier=TaskTier.OPUS,
            rule='destructive_risk',
            confidence=1.0,
            explanation='Destructive risk_level — routing to Opus for safety',
        )

    # ── Rule 2: Critical phrases / words → Opus ───────────────────────────────
    matched_critical = [ph for ph in _CRITICAL_PHRASES if ph in p]
    if not matched_critical:
        matched_critical = [w for w in _CRITICAL_WORDS if w in p.split()]
    if matched_critical:
        return ClassificationResult(
            tier=TaskTier.OPUS,
            rule='critical_signal',
            confidence=1.0,
            explanation=f'Critical signal: {", ".join(matched_critical[:2])}',
        )

    # ── Rule 3: Phloe ORM without tenant filter → Opus ───────────────────────
    if project == 'phloe':
        orm_match = [kw for kw in _PHLOE_ORM_KEYWORDS if kw in p]
        if orm_match:
            return ClassificationResult(
                tier=TaskTier.OPUS,
                rule='phloe_orm_safety',
                confidence=1.0,
                explanation=f'Phloe ORM keyword ({orm_match[0]}) — tenant safety',
            )

    # ── Rule 4: High phrases / words → Sonnet ────────────────────────────────
    matched_high = [ph for ph in _HIGH_PHRASES if ph in p]
    if not matched_high:
        matched_high = [w for w in _HIGH_WORDS if w in p.split()]
    if matched_high:
        # Allow downgrade when signals suggest a minor task
        if _is_downgraded(p):
            return ClassificationResult(
                tier=TaskTier.DEEPSEEK,
                rule='high_downgraded',
                confidence=0.75,
                explanation=(
                    f'High signal ({matched_high[0]}) downgraded '
                    f'by minor-task indicator'
                ),
            )
        return ClassificationResult(
            tier=TaskTier.CLAUDE,
            rule='high_signal',
            confidence=0.90,
            explanation=f'High complexity: {", ".join(matched_high[:2])}',
        )

    # ── Rule 5: Multi-domain + coupling → Sonnet ─────────────────────────────
    domains = _domain_count(p)
    if domains >= 3 and _has_tight_coupling(p):
        return ClassificationResult(
            tier=TaskTier.CLAUDE,
            rule='multi_domain_coupled',
            confidence=0.80,
            explanation=f'{domains} tightly-coupled domains — routing to Sonnet',
        )

    # ── Rule 6: Medium phrases / words → DeepSeek ────────────────────────────
    matched_medium = [ph for ph in _MEDIUM_PHRASES if ph in p]
    if not matched_medium:
        matched_medium = [w for w in _MEDIUM_WORDS if w in p.split()]
    if matched_medium:
        return ClassificationResult(
            tier=TaskTier.DEEPSEEK,
            rule='medium_signal',
            confidence=0.85,
            explanation=f'Medium complexity: {", ".join(matched_medium[:2])}',
        )

    # ── Rule 7: Multiple files in context → DeepSeek ─────────────────────────
    if context_files >= 3:
        return ClassificationResult(
            tier=TaskTier.DEEPSEEK,
            rule='multi_file_context',
            confidence=0.80,
            explanation=f'{context_files} files in context — DeepSeek',
        )

    # ── Rule 8: Review risk → DeepSeek ───────────────────────────────────────
    if risk_level == 'review':
        return ClassificationResult(
            tier=TaskTier.DEEPSEEK,
            rule='review_risk',
            confidence=0.75,
            explanation='Review-level task — DeepSeek',
        )

    # ── Rule 9: Safe + simple read/explain → Local (Tier 1) ──────────────────
    if risk_level == 'safe':
        has_local_verb = any(verb in p for verb in _LOCAL_VERBS)
        if has_local_verb:
            return ClassificationResult(
                tier=TaskTier.LOCAL,
                rule='simple_retrieval',
                confidence=0.85,
                explanation='Safe read/explain task — Local model',
            )

    # ── Default → DeepSeek ───────────────────────────────────────────────────
    return ClassificationResult(
        tier=TaskTier.DEEPSEEK,
        rule='default',
        confidence=0.70,
        explanation='Unclassified — defaulting to DeepSeek',
    )
