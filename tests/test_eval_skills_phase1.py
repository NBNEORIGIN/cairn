from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def test_eval_prompt_suite_loads_expected_prompt_count():
    from core.eval.suite import load_prompt_suite

    suite = load_prompt_suite(Path('projects/deek/eval_prompt_suite.json'))

    assert len(suite) == 10
    assert suite[0].prompt_id == 'chat-request-flow'


def test_eval_score_flags_missing_and_forbidden_markers():
    from core.eval.suite import EvalPrompt, score_answer

    prompt = EvalPrompt(
        prompt_id='demo',
        prompt='Explain DEEK.',
        required_markers=['api/main.py', 'core/agent.py'],
        forbidden_markers=['process_stream()'],
    )

    result = score_answer(prompt, 'It uses api/main.py and process_stream().')

    assert result.passed is False
    assert 'core/agent.py' in result.missing_required
    assert 'process_stream()' in result.forbidden_hits


def test_memory_assembler_exposes_default_budget_constants():
    from core.memory.assembler import MemoryAssembler

    assembler = MemoryAssembler()

    assert assembler.TOTAL_BUDGET_TOKENS == 40_000
    from core.memory.assembler import PROVIDER_BUDGETS
    assert PROVIDER_BUDGETS['sonnet']['total'] == 64_000


def test_skill_manager_resolve_for_request_is_manual_only(tmp_path):
    from core.skills.manager import SkillManager

    skills_root = tmp_path / 'projects' / 'demo' / 'skills' / 'architecture'
    skills_root.mkdir(parents=True)
    (skills_root / 'skill.yaml').write_text(
        '\n'.join([
            'skill_id: architecture',
            'project_id: demo',
            'display_name: Architecture',
            'description: DEEK architecture and request flow',
            'triggers:',
            '  - architecture',
            'key_rules:',
            '  - Keep answers grounded in source files',
        ]),
        encoding='utf-8',
    )

    manager = SkillManager(project_id='demo', projects_root=tmp_path / 'projects')

    assert manager.resolve_for_request('tell me about the architecture') == []
    resolved = manager.resolve_for_request(
        'tell me about the architecture',
        manual_skill_ids=['architecture'],
    )
    assert [skill.skill_id for skill in resolved] == ['architecture']


def test_skill_manager_builds_context_with_recent_decisions(tmp_path):
    from core.skills.manager import SkillManager

    skill_dir = tmp_path / 'projects' / 'demo' / 'skills' / 'runtime'
    skill_dir.mkdir(parents=True)
    (skill_dir / 'skill.yaml').write_text(
        '\n'.join([
            'skill_id: runtime',
            'project_id: demo',
            'display_name: Runtime',
            'description: Runtime hardening and request deadlines',
            'prompt_hint: Prefer useful fallback answers over silent failures',
            'key_rules:',
            '  - Never hang the request loop',
        ]),
        encoding='utf-8',
    )
    (skill_dir / 'decisions.md').write_text(
        '- 2026-03-27: Keep request deadlines under 90 seconds\n',
        encoding='utf-8',
    )

    manager = SkillManager(project_id='demo', projects_root=tmp_path / 'projects')
    skills = manager.resolve(['runtime'])
    block = manager.build_context(skills)

    assert 'Runtime' in block
    assert 'Never hang the request loop' in block
    assert 'Keep request deadlines under 90 seconds' in block


def test_summariser_appends_bullets_to_skill_decisions(tmp_path, monkeypatch):
    import core.memory.summariser as summariser_module
    from core.memory.summariser import SessionSummariser

    monkeypatch.setattr(summariser_module, '_REPO_ROOT', tmp_path)

    skill_dir = tmp_path / 'projects' / 'demo' / 'skills' / 'runtime'
    skill_dir.mkdir(parents=True)

    summariser = SessionSummariser(project_id='demo')
    summariser._append_to_skill_decisions(
        ['runtime'],
        ['Keep stop handling cooperative'],
    )

    decisions_path = skill_dir / 'decisions.md'
    content = decisions_path.read_text(encoding='utf-8')
    assert 'Keep stop handling cooperative' in content


@pytest.mark.asyncio
async def test_process_streaming_emits_response_delta_events():
    from core.agent import DeekAgent
    from core.channels.envelope import Channel, MessageEnvelope

    long_answer = (
        'DEEK routes requests through api/main.py into core/agent.py, then '
        'retrieves context, calls the model, validates the answer, and '
        'streams the finished response back to the web UI.'
    )
    fake_response = (
        long_answer,
        None,
        {'input_tokens': 5, 'output_tokens': 10, 'total_tokens': 15},
    )

    with patch('core.models.claude_client.ClaudeClient.chat', new_callable=AsyncMock) as mock_chat, \
         patch(
             'core.context.engine.ContextEngine.build_context_prompt',
             return_value=('mock ctx', {'context_files': [], 'context_file_count': 0}),
         ):
        mock_chat.return_value = fake_response
        agent = DeekAgent(
            project_id='test',
            config={'name': 'test', 'force_model': 'api', 'permissions': ['read_file']},
        )

        envelope = MessageEnvelope(
            content='Explain the DEEK request flow',
            channel=Channel.WEB,
            project_id='test',
            session_id='stream-delta-test',
        )

        events = []
        async for event in agent.process_streaming(envelope):
            events.append(event)

    delta_events = [event for event in events if event['type'] == 'response_delta']
    assert delta_events
    assert ''.join(event['text'] for event in delta_events).strip()
