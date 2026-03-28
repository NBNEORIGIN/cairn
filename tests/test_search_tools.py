from pathlib import Path


def test_search_code_ignores_virtualenv_and_build_dirs(tmp_path):
    from core.tools.search_tools import _search_code

    (tmp_path / '.venv' / 'Lib').mkdir(parents=True)
    (tmp_path / '.next' / 'server').mkdir(parents=True)
    (tmp_path / 'web' / 'src').mkdir(parents=True)

    (tmp_path / '.venv' / 'Lib' / 'noise.py').write_text(
        'abort controller implementation\n',
        encoding='utf-8',
    )
    (tmp_path / '.next' / 'server' / 'noise.ts').write_text(
        'pages/api/stop.ts\n',
        encoding='utf-8',
    )
    (tmp_path / 'web' / 'src' / 'real.ts').write_text(
        'const stopGeneration = () => fetch("/api/chat/stop")\n',
        encoding='utf-8',
    )

    result = _search_code(str(tmp_path), 'stop')

    assert 'real.ts' in result
    assert '.venv' not in result
    assert '.next' not in result


def test_search_code_uses_smart_case_for_generic_queries(tmp_path):
    from core.tools.search_tools import _search_code

    (tmp_path / 'core').mkdir(parents=True)
    (tmp_path / 'core' / 'agent.py').write_text(
        'class GenerationStopped(Exception):\n    pass\n',
        encoding='utf-8',
    )

    result = _search_code(str(tmp_path), 'stop')

    assert 'GenerationStopped' in result


def test_search_code_falls_back_when_rg_launch_is_denied(tmp_path, monkeypatch):
    import subprocess

    from core.tools.search_tools import _search_code

    (tmp_path / 'web' / 'src').mkdir(parents=True)
    (tmp_path / 'web' / 'src' / 'real.ts').write_text(
        "const route = '/api/chat/stop'\n",
        encoding='utf-8',
    )

    def _raise(*_args, **_kwargs):
        raise PermissionError('[WinError 5] Access is denied')

    monkeypatch.setattr(subprocess, 'run', _raise)

    result = _search_code(str(tmp_path), 'stop', 'web/**/*.ts')

    assert 'real.ts' in result
