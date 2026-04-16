#!/usr/bin/env python3
"""One-shot bulk rename script: cairn/deek -> deek.

Preserves DB table names (claw_code_chunks, cairn_email_raw, etc.),
the cairn@nbnesigns.com email address, and cairn_intel schema name.

Run from repo root: python scripts/rename_cairn_to_deek.py
"""
import os
import re

SKIP_DIRS = {'.venv', '__pycache__', 'node_modules', '.git', '.claude'}
CODE_EXTS = {'.py', '.ps1', '.bat', '.sh', '.json', '.yml', '.yaml',
             '.ts', '.tsx', '.js', '.jsx', '.md', '.html', '.css', '.conf'}

# Patterns that must NOT be touched (DB tables, email, passwords, schema)
PRESERVE_STRINGS = [
    'claw_code_chunks',
    'idx_claw_chunks',
    'cairn_email_raw',
    'cairn_delegation_log',
    'idx_cairn_delegation',
    'cairn_wiki_generation_log',
    'cairn_wiki_gen_log',
    'cairn_intel',
    'cairn@nbnesigns',
    'cairn_nbne_2026',
    'cairn_crm',
]


def should_preserve_line(line):
    ll = line.lower()
    for pat in PRESERVE_STRINGS:
        if pat.lower() in ll:
            return True
    return False


def transform_line(line):
    if should_preserve_line(line):
        return line

    r = line

    # --- File/module import references ---
    r = r.replace('deek_federation', 'deek_federation')
    r = r.replace('deek_tools', 'deek_tools')
    r = r.replace('deek_mcp_server', 'deek_mcp_server')
    r = r.replace('process_deek_inbox', 'process_deek_inbox')
    r = r.replace('evaluate_deek_answers', 'evaluate_deek_answers')
    r = r.replace('test_deek', 'test_deek')
    r = r.replace('deek_tray', 'deek_tray')
    r = r.replace('build_deek_context', 'build_deek_context')

    # --- Class names ---
    r = r.replace('DeekAgent', 'DeekAgent')

    # --- Docker container/service references ---
    r = r.replace('deploy-deek-api-1', 'deploy-deek-api-1')
    r = r.replace('deploy-deek-db-1', 'deploy-deek-db-1')
    r = r.replace('deek-api', 'deek-api')
    r = r.replace('deek-db', 'deek-db')
    r = r.replace('deek-web', 'deek-web')
    r = r.replace('deek-pgdata', 'deek-pgdata')
    r = r.replace('deek-data', 'deek-data')

    # --- Server paths ---
    r = r.replace('/opt/nbne/deek/', '/opt/nbne/deek/')
    r = r.replace('/opt/nbne/deek', '/opt/nbne/deek')

    # --- Script/file references ---
    r = r.replace('build-deek-api', 'build-deek-api')
    r = r.replace('build-deek.bat', 'build-deek.bat')
    r = r.replace('start-deek.bat', 'start-deek.bat')
    r = r.replace('start-deek.bat', 'start-deek.bat')
    r = r.replace('restart-deek.bat', 'restart-deek.bat')
    r = r.replace('stop-deek.bat', 'stop-deek.bat')
    r = r.replace('status-deek.bat', 'status-deek.bat')
    r = r.replace('deek.ps1', 'deek.ps1')
    r = r.replace('deek.bat', 'deek.bat')

    # --- MCP tool names ---
    r = r.replace('deek_delegate', 'deek_delegate')

    # --- Project/docs directory refs ---
    r = r.replace('projects/deek', 'projects/deek')
    r = r.replace("project='deek'", "project='deek'")
    r = r.replace('project="deek"', 'project="deek"')
    r = r.replace('docs/deek', 'docs/deek')

    # --- GitHub repo ---
    r = r.replace('NBNEORIGIN/deek', 'NBNEORIGIN/deek')
    r = r.replace('NBNEORIGIN/deek', 'NBNEORIGIN/deek')

    # --- Domain ---
    r = r.replace('deek.nbnesigns.co.uk', 'deek.nbnesigns.co.uk')

    # --- Env var name replacements (DEEK_ -> DEEK_) ---
    for old in ['DEEK_API_KEY', 'DEEK_API_URL', 'DEEK_BASE_URL',
                'DEEK_EMBED_PROVIDER', 'DEEK_SKIP_AUTO_INDEX',
                'DEEK_REINDEX_INTERVAL_HOURS', 'DEEK_SNAPSHOT_INTERVAL_MINUTES',
                'DEEK_EMAIL_TRIAGE_ENABLED', 'DEEK_TRIAGE_DAILY_LIMIT',
                'DEEK_TRIAGE_DIGEST_TO', 'DEEK_SOCIAL_MODEL', 'DEEK_ROOT',
                'DEEK_HETZNER_HOST', 'DEEK_HETZNER_API_KEY', 'DEEK_WIKI_DIR',
                'DEEK_PRINCIPLES_MAX_FILES', 'DEEK_HARDWARE_PROFILE']:
        r = r.replace(old, old.replace('DEEK_', 'DEEK_'))

    for old in ['DEEK_API_KEY', 'DEEK_DATA_DIR', 'DEEK_FORCE_API',
                'DEEK_ENABLE_WATCHER', 'DEEK_MAX_TIER', 'DEEK_TIER4_PROJECTS',
                'DEEK_REQUEST_TIMEOUT_SECONDS', 'DEEK_MODEL_TIMEOUT_SECONDS']:
        r = r.replace(old, old.replace('CLAW_', 'DEEK_'))

    # --- Variable/function name fragments ---
    r = r.replace('_DEEK_ROOT', '_DEEK_ROOT')
    r = r.replace('deek_context', 'deek_context')
    r = r.replace('deek_url', 'deek_url')
    r = r.replace('deek_memory', 'deek_memory')
    r = r.replace('deek_inbox', 'deek_inbox')

    # --- Service names in Windows scripts ---
    r = r.replace('deek-api', 'deek-api')
    r = r.replace('deek-web', 'deek-web')
    r = r.replace('DeekEmail', 'DeekEmail')
    r = r.replace('DeekInbox', 'DeekInbox')

    # --- Branding in text (case-sensitive) ---
    r = r.replace('[Deek]', '[Deek]')
    r = r.replace('[DEEK', '[DEEK')

    # "Deek" as a standalone word in prose (careful with boundaries)
    # Use regex for word-boundary replacement
    r = re.sub(r'\bCairn\b', 'Deek', r)
    r = re.sub(r'\bCAIRN\b', 'DEEK', r)

    # "deek" as standalone word in variable contexts — but preserve 'deek' when it's
    # a project_id value in SQL queries (already handled by PRESERVE check above)
    r = re.sub(r'\bclaw\b(?!_code_chunks|_dev)', 'deek', r)
    r = re.sub(r'\bCLAW\b', 'DEEK', r)

    # Catch remaining DEEK_ prefixed strings
    r = r.replace('DEEK_', 'DEEK_')

    return r


def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            original = f.read()
    except Exception:
        return 0

    lines = original.splitlines(True)
    new_lines = [transform_line(line) for line in lines]
    new_content = ''.join(new_lines)

    if new_content != original:
        changed = sum(1 for o, n in zip(lines, new_lines) if o != n)
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        return changed
    return 0


def main():
    total_files = 0
    total_changes = 0

    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in CODE_EXTS:
                continue
            filepath = os.path.join(root, fname)
            changes = process_file(filepath)
            if changes > 0:
                total_files += 1
                total_changes += changes
                if changes > 3:
                    print(f'  {filepath}: {changes} lines')

    print(f'\nDone: {total_files} files, {total_changes} lines changed')


if __name__ == '__main__':
    main()
