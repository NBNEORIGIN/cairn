"""
Memory Assembler — Layer 2: budget-aware prompt assembly with provider-specific formatting.

Assembles context from multiple sources (core rules, skills, recent messages,
retrieved chunks, @ mentions) into a MemoryPacket, then formats it for the
target provider with appropriate cache control headers.

Phase 1 legacy interface (MemoryAssembly, sync assemble()) is preserved for
backward compatibility until all call sites are migrated.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

PROVIDER_BUDGETS: dict[str, dict[str, int]] = {
    'ollama': {
        'total':           4_000,
        'core_rules':        400,
        'skill_context':     300,
        'recent_messages': 1_500,
        'retrieved':       1_800,
    },
    'local': {
        'total':           4_000,
        'core_rules':        400,
        'skill_context':     300,
        'recent_messages': 1_500,
        'retrieved':       1_800,
    },
    'deepseek': {
        'total':          32_000,
        'core_rules':      1_000,
        'skill_context':   1_500,
        'recent_messages': 3_000,
        'retrieved':      26_500,
    },
    'sonnet': {
        'total':          64_000,
        'core_rules':      2_000,
        'skill_context':   2_000,
        'recent_messages': 5_000,
        'retrieved':      55_000,
    },
    'claude': {
        'total':          64_000,
        'core_rules':      2_000,
        'skill_context':   2_000,
        'recent_messages': 5_000,
        'retrieved':      55_000,
    },
    'opus': {
        'total':         100_000,
        'core_rules':      2_000,
        'skill_context':   3_000,
        'recent_messages': 8_000,
        'retrieved':      87_000,
    },
    'gpt54': {
        'total':          64_000,
        'core_rules':      2_000,
        'skill_context':   2_000,
        'recent_messages': 5_000,
        'retrieved':      55_000,
    },
    'openai': {
        'total':          64_000,
        'core_rules':      2_000,
        'skill_context':   2_000,
        'recent_messages': 5_000,
        'retrieved':      55_000,
    },
}

# ── Phase 1 backward-compat ──────────────────────────────────────────────────


@dataclass
class MemoryAssembly:
    """Phase 1 return type — single prompt string + metadata."""
    prompt: str
    metadata: dict = field(default_factory=dict)


# ── Phase 2 ──────────────────────────────────────────────────────────────────


@dataclass
class MemoryPacket:
    """Full structured memory assembly with per-section detail."""
    core_rules: str
    skill_context: Optional[str]
    recent_messages: list[dict]
    retrieved_chunks: list[dict]
    mentioned_context: list[dict]
    active_skills: list[str]
    provider: str
    total_tokens_estimated: int
    budget_used_pct: float
    cacheable_sections: list[str]
    bm25_hits: int
    cosine_hits: int
    both_hits: int


class MemoryAssembler:
    """
    Budget-aware prompt assembly for the current agent/context contracts.

    Phase 2: structured MemoryPacket output with provider-specific formatting
    and prompt caching support.
    """

    # Backward compat: flat total budgets per provider
    TOTAL_BUDGET_TOKENS = 40_000
    SKILL_BUDGET_TOKENS = 900
    HISTORY_BUDGET_TOKENS = 2_400

    def __init__(
        self,
        retriever=None,
        store=None,
        project_configs: dict | None = None,
    ):
        self.retriever = retriever
        self.store = store
        self.project_configs = project_configs or {}

    # ── Token estimation ─────────────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """Word count × 1.3 — no tokenizer library needed."""
        if not text:
            return 0
        return int(len(text.split()) * 1.3)

    # Keep old name as alias
    def estimate_tokens(self, text: str) -> int:
        return self._estimate_tokens(text)

    def _trim_text_to_budget(self, text: str, budget_tokens: int) -> str:
        if not text:
            return ''
        words = text.split()
        max_words = max(1, int(budget_tokens / 1.3))
        if len(words) <= max_words:
            return text
        return ' '.join(words[:max_words]) + ' …'

    # ── Core rules distillation ──────────────────────────────────────────────

    def _distill_core_rules(self, project_id: str) -> str:
        """
        Read projects/{project_id}/core.md.
        Extract sections: ## Rules, ## Constraints, ## Anti-patterns, ## Key Decisions.
        If none found: first 400 words.
        Hard cap: 500 words regardless.
        """
        core_path = _REPO_ROOT / 'projects' / project_id / 'core.md'
        if not core_path.exists():
            return ''

        try:
            core_text = core_path.read_text(encoding='utf-8')
        except Exception:
            return ''

        return self.distill_core_rules(core_text)

    def distill_core_rules(self, core_text: str, budget_tokens: int = 1_800) -> str:
        """Extract key sections from core.md text, capped to budget."""
        patterns = (
            r'##\s+Rules.*?(?=\n##\s+|\Z)',
            r'##\s+Constraints.*?(?=\n##\s+|\Z)',
            r'##\s+Anti-patterns.*?(?=\n##\s+|\Z)',
            r'##\s+Key Decisions.*?(?=\n##\s+|\Z)',
            r'##\s+Architecture.*?(?=\n##\s+|\Z)',
        )
        extracted: list[str] = []
        for pattern in patterns:
            match = re.search(pattern, core_text, re.DOTALL | re.IGNORECASE)
            if match:
                extracted.append(match.group(0).strip())
        if extracted:
            result = '\n\n'.join(extracted)
        else:
            result = ' '.join(core_text.split()[:400])

        # Hard cap: 500 words
        words = result.split()
        if len(words) > 500:
            result = ' '.join(words[:500]) + ' …'

        return self._trim_text_to_budget(result, budget_tokens)

    # ── Phase 2: async assemble ──────────────────────────────────────────────

    async def assemble(
        self,
        query: str = '',
        project_id: str = '',
        session_id: str = '',
        provider: str = 'sonnet',
        subproject_id: Optional[str] = None,
        skill_ids: list[str] | None = None,
        mentions: list | None = None,
        # Phase 1 backward-compat kwargs
        base_context_prompt: str | None = None,
        history: list[dict] | None = None,
        skill_blocks: list[str] | None = None,
    ) -> MemoryPacket:
        """
        Assembly order (greedy, highest priority first):
        1. core_rules — distilled core.md rules section
        2. skill_context — if skill_ids provided
        3. recent_messages — last N from store
        4. mentioned_context — @ mention resolutions
        5. retrieved_chunks — hybrid retrieval, remaining budget
        6. trim to budget
        7. mark cacheable sections
        """
        skill_ids = skill_ids or []
        mentions = mentions or []
        budget = PROVIDER_BUDGETS.get(provider, PROVIDER_BUDGETS['sonnet'])
        total_budget = budget['total']
        tokens_used = 0

        # 1. Core rules
        core_rules = self._distill_core_rules(project_id) if project_id else ''
        core_rules = self._trim_text_to_budget(core_rules, budget['core_rules'])
        core_tokens = self._estimate_tokens(core_rules)
        tokens_used += core_tokens

        # 2. Skill context
        skill_context: str | None = None
        if skill_ids and self.project_configs:
            skill_blocks_list = self._load_skill_blocks(project_id, skill_ids)
            if skill_blocks_list:
                raw = '\n\n'.join(skill_blocks_list)
                skill_context = self._trim_text_to_budget(raw, budget['skill_context'])
        skill_tokens = self._estimate_tokens(skill_context or '')
        tokens_used += skill_tokens

        # 3. Recent messages
        recent_messages: list[dict] = []
        if self.store and session_id:
            recent_messages = self.store.get_recent_history(session_id, limit=20)
        elif history is not None:
            recent_messages = list(history)

        # Trim messages to budget
        msg_budget = budget['recent_messages']
        trimmed_messages: list[dict] = []
        msg_tokens = 0
        for msg in reversed(recent_messages):
            content = msg.get('content', '')
            est = self._estimate_tokens(content)
            if msg_tokens + est > msg_budget and trimmed_messages:
                break
            trimmed_messages.insert(0, msg)
            msg_tokens += est
        recent_messages = trimmed_messages
        tokens_used += msg_tokens

        # 4. Mentioned context
        mentioned_context: list[dict] = []
        mention_tokens = 0
        for mention in mentions:
            content = mention.get('content', '')
            est = self._estimate_tokens(content)
            if tokens_used + est > total_budget and mentioned_context:
                break
            mentioned_context.append(mention)
            mention_tokens += est
            tokens_used += est

        # 5. Retrieved chunks — fill remaining budget
        retrieved_budget = min(
            budget['retrieved'],
            total_budget - tokens_used,
        )
        retrieved_chunks: list[dict] = []
        bm25_hits = 0
        cosine_hits = 0
        both_hits = 0
        retrieved_tokens = 0

        if self.retriever and query and self.retriever.is_available:
            try:
                raw_chunks = self.retriever.retrieve(
                    task=query,
                    embedding_fn=self._noop_embedding,
                    subproject_id=subproject_id,
                )
                for chunk in raw_chunks:
                    chunk_tokens = self._estimate_tokens(chunk.get('content', ''))
                    if retrieved_tokens + chunk_tokens > retrieved_budget and retrieved_chunks:
                        # Always keep at least 3 chunks
                        if len(retrieved_chunks) >= 3:
                            break
                    retrieved_chunks.append(chunk)
                    retrieved_tokens += chunk_tokens

                    quality = chunk.get('match_quality', 'semantic')
                    if quality == 'exact+semantic':
                        both_hits += 1
                    elif quality == 'exact':
                        bm25_hits += 1
                    else:
                        cosine_hits += 1
            except Exception as exc:
                logger.warning('[assembler] retrieval failed: %s', exc)

        tokens_used += retrieved_tokens

        budget_pct = min(100.0, round((tokens_used / max(total_budget, 1)) * 100, 1))

        cacheable = ['core_rules']
        if skill_context:
            cacheable.append('skill_context')

        return MemoryPacket(
            core_rules=core_rules,
            skill_context=skill_context,
            recent_messages=recent_messages,
            retrieved_chunks=retrieved_chunks,
            mentioned_context=mentioned_context,
            active_skills=skill_ids,
            provider=provider,
            total_tokens_estimated=tokens_used,
            budget_used_pct=budget_pct,
            cacheable_sections=cacheable,
            bm25_hits=bm25_hits,
            cosine_hits=cosine_hits,
            both_hits=both_hits,
        )

    # ── Provider formatting ──────────────────────────────────────────────────

    def format_for_provider(
        self,
        packet: MemoryPacket,
        provider: str,
    ) -> list[dict]:
        """
        Convert packet to provider message format.

        Anthropic (sonnet/opus): cache_control on core_rules and skill_context blocks.
        Others (deepseek/openai/ollama): plain string content, no cache_control.
        """
        is_anthropic = provider in ('sonnet', 'opus', 'claude')

        if is_anthropic:
            return self._format_anthropic(packet)
        return self._format_openai_compat(packet, provider)

    def _format_anthropic(self, packet: MemoryPacket) -> list[dict]:
        """Anthropic message format with cache_control blocks."""
        messages: list[dict] = []

        # System message 1: core rules + skill context
        system_blocks: list[dict] = []
        if packet.core_rules:
            system_blocks.append({
                'type': 'text',
                'text': f'# Project Rules\n{packet.core_rules}',
                'cache_control': {'type': 'ephemeral'},
            })
        if packet.skill_context:
            system_blocks.append({
                'type': 'text',
                'text': f'# Active Skills\n{packet.skill_context}',
                'cache_control': {'type': 'ephemeral'},
            })

        if system_blocks:
            messages.append({'role': 'system', 'content': system_blocks})

        # System message 2: retrieved chunks with quality labels
        if packet.retrieved_chunks:
            chunk_text = self._format_retrieved_chunks(packet.retrieved_chunks)
            messages.append({
                'role': 'system',
                'content': f'# Retrieved Context\n{chunk_text}',
            })

        # System message 3: mentioned context
        if packet.mentioned_context:
            mention_text = self._format_mentions(packet.mentioned_context)
            messages.append({
                'role': 'system',
                'content': f'# Pinned Context\n{mention_text}',
            })

        # Recent messages as user/assistant turns
        for msg in packet.recent_messages:
            role = msg.get('role', 'user')
            if role in ('user', 'assistant'):
                messages.append({'role': role, 'content': msg.get('content', '')})

        return messages

    def _format_openai_compat(self, packet: MemoryPacket, provider: str) -> list[dict]:
        """OpenAI/DeepSeek/Ollama format — plain string content."""
        messages: list[dict] = []

        # System message: core rules + skill context combined
        system_parts: list[str] = []
        if packet.core_rules:
            system_parts.append(f'# Project Rules\n{packet.core_rules}')
        if packet.skill_context:
            system_parts.append(f'# Active Skills\n{packet.skill_context}')
        if packet.retrieved_chunks:
            chunk_text = self._format_retrieved_chunks(packet.retrieved_chunks)
            system_parts.append(f'# Retrieved Context\n{chunk_text}')
        if packet.mentioned_context:
            mention_text = self._format_mentions(packet.mentioned_context)
            system_parts.append(f'# Pinned Context\n{mention_text}')

        if system_parts:
            messages.append({
                'role': 'system',
                'content': '\n\n'.join(system_parts),
            })

        # Recent messages as user/assistant turns
        for msg in packet.recent_messages:
            role = msg.get('role', 'user')
            if role in ('user', 'assistant'):
                messages.append({'role': role, 'content': msg.get('content', '')})

        return messages

    def _format_retrieved_chunks(self, chunks: list[dict]) -> str:
        """Format chunks with quality labels."""
        lines: list[str] = []
        for chunk in chunks:
            quality = chunk.get('match_quality', 'semantic')
            file_path = chunk.get('file', 'unknown')
            chunk_type = chunk.get('chunk_type', 'code')
            content = chunk.get('content', '')

            if chunk_type in ('code', 'window', 'function', 'class'):
                label = f'[code: {file_path}]'
            elif chunk_type == 'session':
                label = f'[session: {file_path}]'
            elif chunk_type == 'decision':
                label = f'[decision: {file_path}]'
            else:
                label = f'[{chunk_type}: {file_path}]'

            lines.append(f'{label} ({quality} match)\n{content}')
        return '\n\n'.join(lines)

    def _format_mentions(self, mentions: list[dict]) -> str:
        """Format @ mention resolutions."""
        lines: list[str] = []
        for mention in mentions:
            label = mention.get('label', mention.get('file', 'unknown'))
            content = mention.get('content', '')
            lines.append(f'[pinned: {label}]\n{content}')
        return '\n\n'.join(lines)

    def _load_skill_blocks(self, project_id: str, skill_ids: list[str]) -> list[str]:
        """Load skill context blocks from disk."""
        blocks: list[str] = []
        for skill_id in skill_ids:
            skill_path = _REPO_ROOT / 'projects' / project_id / 'skills' / skill_id / 'context.md'
            if skill_path.exists():
                try:
                    blocks.append(skill_path.read_text(encoding='utf-8'))
                except Exception:
                    pass
        return blocks

    @staticmethod
    def _noop_embedding(text: str):
        """Placeholder embedding function when no real embedder is available."""
        return None

    # ── Phase 1 backward-compat ──────────────────────────────────────────────

    def _format_history(self, history: list[dict]) -> str:
        lines: list[str] = []
        for msg in history[-10:]:
            role = str(msg.get('role', 'user')).upper()
            content = ' '.join(str(msg.get('content', '')).split())
            if not content:
                continue
            lines.append(f'[{role}] {content}')
        return '\n'.join(lines)

    def _trim_history(self, history: list[dict]) -> tuple[str, int]:
        formatted = self._format_history(history)
        trimmed = self._trim_text_to_budget(formatted, self.HISTORY_BUDGET_TOKENS)
        if not trimmed:
            return '', 0
        message_count = len([line for line in trimmed.splitlines() if line.strip().startswith('[')])
        return trimmed, message_count

    def _trim_skill_blocks(self, skill_blocks: list[str]) -> str:
        if not skill_blocks:
            return ''
        block = '\n\n'.join(skill_blocks)
        return self._trim_text_to_budget(block, self.SKILL_BUDGET_TOKENS)

    def assemble_legacy(
        self,
        base_context_prompt: str,
        history: list[dict],
        provider: str,
        skill_blocks: list[str] | None = None,
    ) -> MemoryAssembly:
        """Phase 1 sync assembly — returns single prompt string."""
        budget_total = int(
            PROVIDER_BUDGETS.get(provider, PROVIDER_BUDGETS['sonnet']).get('total', 64_000)
        )
        skills_text = self._trim_skill_blocks(skill_blocks or [])
        history_text, history_messages = self._trim_history(history)

        parts = [base_context_prompt.rstrip()]
        if skills_text:
            parts.append('\n\n=== ACTIVE SKILLS ===\n')
            parts.append(skills_text)
            parts.append('\n=== END ACTIVE SKILLS ===')
        if history_text:
            parts.append('\n\n=== RECENT CONVERSATION ===\n')
            parts.append(history_text)
            parts.append('\n=== END RECENT CONVERSATION ===')

        prompt = ''.join(parts).strip() + '\n'
        budget_used = self._estimate_tokens(prompt)
        metadata = {
            'provider': provider,
            'budget_total': budget_total,
            'budget_used': budget_used,
            'budget_pct': min(100.0, round((budget_used / max(budget_total, 1)) * 100, 1)),
            'history_messages': history_messages,
            'skill_tokens': self._estimate_tokens(skills_text),
            'history_tokens': self._estimate_tokens(history_text),
        }
        return MemoryAssembly(prompt=prompt, metadata=metadata)
