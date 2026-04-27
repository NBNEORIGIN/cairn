"""PostToolUse hook — validate any brief edit against the repo state.

Reads tool-call JSON from stdin, filters to Edit/Write events on
briefs/*.md, runs scripts/validate_brief.py, prints the output for
Claude. Non-blocking: tool already succeeded, we just emit a warning
if the brief now references things that don't exist.

Exit codes:
  0 — silent success or non-target file (no feedback to Claude)
  2 — validator flagged unverified references; stderr shown to Claude

The hook prints to stderr on exit-2 so Claude sees the warning as
"Stop hook feedback"-style context.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / 'scripts' / 'validate_brief.py'


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Malformed input — don't block the user
        return 0

    tool_input = payload.get('tool_input') or {}
    file_path = tool_input.get('file_path') or ''
    if not file_path:
        return 0

    # Normalise to a Path and check it's inside briefs/ AND a markdown file
    p = Path(file_path)
    try:
        rel = p.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return 0  # outside the repo — not our concern
    parts = rel.parts
    if not parts or parts[0] != 'briefs':
        return 0
    if p.suffix.lower() != '.md':
        return 0
    if not VALIDATOR.exists():
        return 0

    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(p)],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        print('[validate-brief hook] timed out', file=sys.stderr)
        return 0
    except Exception as exc:
        print(f'[validate-brief hook] failed to run: {exc}', file=sys.stderr)
        return 0

    # Validator exits 0 when everything checks, 1 when there are
    # unverified references. We pipe its stdout to stderr on failure
    # so it's surfaced to Claude as feedback (exit-2 semantics).
    if result.returncode == 1:
        sys.stderr.write(result.stdout or '')
        sys.stderr.write(result.stderr or '')
        return 2

    # Clean run — silent
    return 0


if __name__ == '__main__':
    sys.exit(main())
