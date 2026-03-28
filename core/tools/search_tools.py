"""
Code search tools — ripgrep-backed for speed, fallback to Python glob.
"""
import subprocess
import fnmatch
from pathlib import Path
from .registry import Tool, RiskLevel

_SKIP_DIRS = {
    '.git',
    '.venv',
    'venv',
    'node_modules',
    '.next',
    '__pycache__',
    'dist',
    'build',
}


def _search_code(
    project_root: str,
    query: str,
    file_pattern: str = '',
) -> str:
    """
    Search the project codebase for a pattern.
    Uses ripgrep if available, falls back to Python glob+re.
    Returns matched lines with file and line number.
    """
    root = Path(project_root)
    if not root.exists():
        return f"ERROR: Project root not found: {project_root}"

    # Try ripgrep first (much faster on large codebases)
    rg_args = ['rg', '--line-number', '--no-heading', '--color', 'never', '--smart-case']
    for dirname in _SKIP_DIRS:
        rg_args += ['--glob', f'!**/{dirname}/**']
    if file_pattern:
        rg_args += ['--glob', file_pattern]
    rg_args += ['--', query, '.']

    try:
        result = subprocess.run(
            rg_args,
            capture_output=True, text=True, timeout=30, cwd=str(root),
        )
        if result.returncode in (0, 1):  # 1 = no matches, not an error
            output = result.stdout.strip()
            if not output:
                return f"No matches found for: {query}"
            lines = output.splitlines()
            # Truncate to 100 results to keep context manageable
            if len(lines) > 100:
                lines = lines[:100]
                lines.append(f"... (truncated, {len(output.splitlines()) - 100} more matches)")
            return '\n'.join(lines)
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError, OSError):
        pass  # ripgrep not available, fall back

    # Python fallback
    import re
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    results = []
    for filepath in root.rglob('*'):
        if not filepath.is_file():
            continue
        if any(part in _SKIP_DIRS for part in filepath.parts):
            continue
        rel_path = str(filepath.relative_to(root)).replace('\\', '/')
        if file_pattern and not (
            fnmatch.fnmatch(rel_path, file_pattern)
            or fnmatch.fnmatch(filepath.name, file_pattern)
        ):
            continue
        # Skip binary and large files
        if filepath.suffix in {'.pyc', '.png', '.jpg', '.gif', '.ico', '.woff'}:
            continue
        try:
            text = filepath.read_text(encoding='utf-8', errors='ignore')
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    results.append(f"{rel_path}:{i}:{line.strip()}")
                    if len(results) >= 100:
                        results.append("... (truncated)")
                        return '\n'.join(results)
        except Exception:
            continue

    return '\n'.join(results) if results else f"No matches found for: {query}"


search_code_tool = Tool(
    name='search_code',
    description=(
        'Search the project codebase for a string or regex pattern. '
        'Returns file:line:content matches. '
        'Optionally filter by file_pattern e.g. "*.py".'
    ),
    risk_level=RiskLevel.SAFE,
    fn=_search_code,
    required_permission='search_code',
)
