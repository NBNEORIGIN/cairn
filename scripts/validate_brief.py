"""Validate references in a brief (briefs/*.md) against the repo.

Catches the mechanical errors that wasted a fresh session's first 30
minutes on Layer 2:
  * file paths that don't exist on disk (`reply_normaliser.py`)
  * SQL tables that don't exist (`cairn_memory_writes`)
  * Python symbols / function names that don't exist anywhere
  * HTTP endpoints that aren't wired into any route

Heuristic — false negatives are fine (a new symbol the brief is asking
to create won't be flagged), false positives waste implementer time
so we lean conservative.

Usage:
    python scripts/validate_brief.py briefs/some-brief.md

Exits 0 if every detected reference resolves, 1 if any unverified, 2
on usage errors.
"""
from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories to skip when walking the repo (build/cache/data dirs +
# cloned tenant repos under data/repos/* and .claude/worktrees/*). We
# DO include briefs/ and projects/ — a brief can legitimately reference
# another brief, and projects/ contains real repo content like
# projects/jo/identity.md. Self-validation (the current brief matching
# its own contents) is handled separately via _self_path.
_GREP_SKIP_DIRS = {
    '.venv', 'venv', 'node_modules', '.next', '__pycache__',
    '.git', 'wiki/_meta', '.tmp', 'dist', 'build',
    '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'worktrees',  # .claude/worktrees — old agent branches
    'repos',      # data/repos — cloned tenant repos
}

# Path of the brief currently being validated. Excluded from grep_fixed
# / grep_regex so a brief doesn't self-validate by its own contents.
_self_path: Path | None = None

# Absolute paths that aren't repo paths (server filesystem, /etc, /opt, etc.)
_ABS_SERVER_PREFIXES = (
    '/opt/', '/etc/', '/var/', '/usr/', '/home/', '/root/',
    '/tmp/', '/srv/', '/dev/', '/proc/', '/sys/', '/mnt/',
    'C:/', 'D:/', 'C:\\', 'D:\\',
)
_GREP_FILE_EXCLUDE_EXT = {'.pyc', '.lock', '.png', '.jpg', '.jpeg', '.gif',
                          '.pdf', '.zip', '.gz', '.exe', '.dll', '.so',
                          '.woff', '.woff2', '.ttf', '.ico', '.svg'}
_GREP_INCLUDE_EXT = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.md', '.json', '.sql',
    '.yaml', '.yml', '.sh', '.ps1', '.toml', '.html', '.css', '.txt',
    '.bat', '.env',
}

# Extensions that we'll treat as "looks like a real source path"
FILE_EXTS = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.md', '.json', '.sql',
    '.yaml', '.yml', '.sh', '.ps1', '.toml', '.html', '.css', '.txt',
    '.bat', '.env',
}

INLINE_CODE_RE = re.compile(r'`([^`\n]+)`')
LINK_RE = re.compile(r'\[[^\]]+\]\(([^)\s#]+)(?:\s+[^)]*)?\)')
ENDPOINT_RE = re.compile(r'(?<![A-Za-z0-9_])(/api/[a-zA-Z0-9_/\-{}]+)')

# Skip noise — these appear in backticks but aren't references we can verify
NOISE_TOKENS = frozenset({
    'true', 'false', 'null', 'none', 'yes', 'no',
    'TRUE', 'FALSE', 'YES', 'NO', 'LATER',
    'GET', 'POST', 'PUT', 'DELETE', 'PATCH',
})


def is_file_path(s: str) -> bool:
    s = s.strip()
    if not s or ' ' in s or s in NOISE_TOKENS:
        return False
    if s.startswith(('http://', 'https://', 'ssh://', 'mailto:')):
        return False
    # Server paths aren't repo paths — skip
    if s.startswith(_ABS_SERVER_PREFIXES):
        return False
    # API endpoint paths get their own detector
    if s.startswith('/api/'):
        return False
    if '/' not in s and '\\' not in s:
        return False
    # Strip line-suffix like foo.py:123 before extension check
    head = s.split(':')[0]
    ext = os.path.splitext(head)[1].lower()
    return ext in FILE_EXTS or head.endswith('/')


def is_bare_filename(s: str) -> bool:
    """`Foo.tsx` or `identity.md` — a single-segment filename with a
    recognised extension. Treated separately from python symbols so
    we can match against actual file names in the walk, not just
    string content (TS imports drop `.tsx` from import specifiers)."""
    s = s.strip()
    if not s or '/' in s or '\\' in s:
        return False
    if s.count('.') != 1:
        return False
    name, ext = os.path.splitext(s)
    if not name or not ext:
        return False
    return ext.lower() in FILE_EXTS


def is_python_symbol(s: str) -> bool:
    """A function-call shape `name()` or dotted path `mod.sub.attr`."""
    s = s.strip()
    if s in NOISE_TOKENS:
        return False
    # Bare filenames are not symbols — handle separately
    if is_bare_filename(s):
        return False
    if re.fullmatch(r'_?[a-zA-Z][a-zA-Z0-9_]*\(\)', s):
        return True
    if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*){1,4}', s):
        return True
    return False


@lru_cache(maxsize=1)
def _all_filenames_index() -> dict[str, list[Path]]:
    """basename -> list of paths that have that basename. Lets us
    answer 'does any file in the repo end with /BriefCard.tsx?' in
    O(1) instead of walking the tree per query."""
    idx: dict[str, list[Path]] = {}
    for p in _all_text_files():
        idx.setdefault(p.name, []).append(p)
    return idx


def filename_exists(name: str) -> bool:
    return name in _all_filenames_index()


def is_sql_table(s: str) -> bool:
    """snake_case with >=2 underscores, plausible table-name length."""
    s = s.strip()
    if s in NOISE_TOKENS:
        return False
    if not re.fullmatch(r'[a-z][a-z0-9_]+', s):
        return False
    if s.count('_') < 2:
        return False
    return 8 <= len(s) <= 60


def file_exists(rel_path: str) -> bool:
    p = rel_path.split(':')[0].rstrip('/')
    return (REPO_ROOT / p).exists()


@lru_cache(maxsize=1)
def _all_text_files() -> list[Path]:
    """Walk the repo once and cache the list of files we're willing to
    grep. Skips data/, .venv/, node_modules/, etc."""
    out: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Prune skip dirs in-place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if d not in _GREP_SKIP_DIRS]
        rel_root = Path(root).relative_to(REPO_ROOT)
        # Skip nested wiki/_meta etc.
        if any(part in _GREP_SKIP_DIRS for part in rel_root.parts):
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _GREP_FILE_EXCLUDE_EXT:
                continue
            # If it has an unknown extension, skip — we want to grep
            # source-ish files only.
            if ext and ext not in _GREP_INCLUDE_EXT:
                continue
            out.append(Path(root) / f)
    return out


@lru_cache(maxsize=1)
def _all_sql_files() -> list[Path]:
    return [p for p in _all_text_files() if p.suffix.lower() == '.sql']


def grep_fixed(pattern: str) -> bool:
    """Substring grep across the repo. Skips the brief being validated
    so a brief doesn't satisfy its own grep checks."""
    needle = pattern
    for fp in _all_text_files():
        if _self_path and fp.resolve() == _self_path:
            continue
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                if needle in fh.read():
                    return True
        except OSError:
            continue
    return False


def grep_regex(pattern: str) -> bool:
    """Regex grep across the repo. Skips the brief being validated."""
    try:
        rx = re.compile(pattern)
    except re.error:
        return False
    for fp in _all_text_files():
        if _self_path and fp.resolve() == _self_path:
            continue
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                if rx.search(fh.read()):
                    return True
        except OSError:
            continue
    return False


def grep_sql_table(name: str) -> bool:
    """Look for CREATE TABLE … <name> in any .sql or .py file. Some
    DDL is issued from Python (e.g. core/context/indexer.py creates
    claw_code_chunks at startup) rather than living in migrations/."""
    rx = re.compile(
        rf'CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?[\w.]*{re.escape(name)}\b',
        re.IGNORECASE,
    )
    for fp in _all_text_files():
        if fp.suffix.lower() not in {'.sql', '.py'}:
            continue
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                if rx.search(fh.read()):
                    return True
        except OSError:
            continue
    return False


def grep_endpoint(path: str) -> bool:
    """Hit if the literal path OR the router-stripped form (e.g.
    /brief/today when mounted under /api/deek) appears in api/."""
    candidates = [path]
    parts = path.split('/')
    if len(parts) > 3 and parts[1] == 'api':
        # /api/<bucket>/<rest...> -> /<rest...>
        candidates.append('/' + '/'.join(parts[3:]))
    for c in candidates:
        if grep_fixed(c):
            return True
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: validate_brief.py <path-to-brief.md>', file=sys.stderr)
        return 2
    target = Path(sys.argv[1]).expanduser().resolve()
    if not target.exists():
        print(f'{target}: not found', file=sys.stderr)
        return 2

    global _self_path
    _self_path = target

    text = target.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()

    findings: list[tuple[int, str, str, bool, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str, line_no: int, ok: bool, note: str) -> None:
        key = (kind, value)
        if key in seen:
            return
        seen.add(key)
        findings.append((line_no, kind, value, ok, note))

    in_code_block = False
    for i, line in enumerate(lines, 1):
        # Skip fenced code blocks — too many false positives in shell
        # examples / config snippets
        if line.lstrip().startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        for m in INLINE_CODE_RE.finditer(line):
            tok = m.group(1).strip()
            if not tok:
                continue
            if is_file_path(tok):
                ok = file_exists(tok)
                add('file', tok, i, ok,
                    'on disk' if ok else 'NOT FOUND on disk')
            elif is_bare_filename(tok):
                ok = filename_exists(tok)
                add('filename', tok, i, ok,
                    f'matches {filename_exists(tok) and len(_all_filenames_index().get(tok, []))} file(s)' if ok
                    else 'no file with this basename')
            elif is_python_symbol(tok):
                if tok.endswith('()'):
                    name = tok[:-2]
                    ok = grep_regex(rf'\b(def|class)\s+{re.escape(name)}\b') \
                         or grep_fixed(name)
                else:
                    # mod.sub.attr — the leaf often appears in a from/import
                    leaf = tok.split('.')[-1]
                    ok = grep_fixed(tok) or grep_regex(
                        rf'\bimport\s+{re.escape(leaf)}\b'
                        rf'|\bfrom\s+\S+\s+import\s+.*{re.escape(leaf)}'
                    )
                add('symbol', tok, i, ok,
                    'grep hit' if ok else 'NOT FOUND in repo')
            elif is_sql_table(tok):
                # Order matters: CREATE TABLE first (definitive), then
                # function-def grep (means it's a function, not a table —
                # demote to symbol). Bare grep-hit alone isn't enough
                # because the brief itself was the only mention.
                if grep_sql_table(tok):
                    add('table', tok, i, True, 'in migrations')
                elif grep_regex(rf'\b(def|function)\s+{re.escape(tok)}\b'):
                    add('symbol', tok, i, True,
                        'matches function name, not a table')
                elif grep_fixed(tok):
                    add('table?', tok, i, False,
                        'mentioned in code but no CREATE TABLE — verify')
                else:
                    add('table?', tok, i, False,
                        'NOT FOUND (no CREATE TABLE, no grep hit)')

        for m in LINK_RE.finditer(line):
            target_path = m.group(1).strip()
            if target_path.startswith(('http://', 'https://', 'mailto:')):
                continue
            if not target_path or target_path.startswith('#'):
                continue
            ok = file_exists(target_path)
            add('link', target_path, i, ok,
                'on disk' if ok else 'NOT FOUND on disk')

        for m in ENDPOINT_RE.finditer(line):
            ep = m.group(1).strip().rstrip('.,)')
            ok = grep_endpoint(ep)
            add('endpoint', ep, i, ok,
                'route exists' if ok else 'NOT FOUND in api/')

    rel = target.relative_to(REPO_ROOT) if str(target).startswith(str(REPO_ROOT)) else target
    print(f'\nValidating {rel}\n')

    if not findings:
        print('  no references detected (brief contains no backticked paths/symbols/endpoints).\n')
        return 0

    for line_no, kind, value, ok, note in findings:
        mark = 'OK' if ok else '!!'
        print(f'  L{line_no:>4} [{kind:>8}] {mark}  {value}  -- {note}')

    failures = [f for f in findings if not f[3]]
    print()
    print(f'  {len(findings)} references checked, {len(failures)} unverified.')

    if failures:
        print()
        print('  Unverified references may be design intent (new files/symbols/')
        print('  tables to create as part of this brief) or factual errors.')
        print('  Read carefully before implementing.')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
