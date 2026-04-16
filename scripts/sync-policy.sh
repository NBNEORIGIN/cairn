#!/usr/bin/env bash
# sync-policy.sh
# Pulls latest NBNE policy documents into a module repo's root.
#
# Usage:
#   bash scripts/sync-policy.sh                 (default — pull from GitHub)
#   bash scripts/sync-policy.sh --from-local    (pull from /opt/nbne/policy/ on Hetzner)
#
# Run by:
#   - Developers locally before starting work on a module
#   - GitHub Actions before every deploy (see SETUP.md for workflow snippet)
#   - Hetzner host cron, optional, to keep /opt/nbne/policy/ fresh
#
# Failure mode: if the sync fails, the existing vendored copies are restored
# from backup. The script never leaves the module in a half-synced state.

set -euo pipefail

POLICY_REPO="https://github.com/NBNEORIGIN/nbne-policy.git"
LOCAL_MIRROR="/opt/nbne/policy"
TEMP_DIR=$(mktemp -d)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$MODULE_ROOT/.policy-backup-$$"

POLICY_FILES=(
    "NBNE_PROTOCOL.md"
    "LOCAL_CONVENTIONS.md"
    "DEEK_MODULES.md"
)

USE_LOCAL=false
if [ "${1:-}" = "--from-local" ]; then
    USE_LOCAL=true
fi

cleanup() {
    rm -rf "$TEMP_DIR" "$BACKUP_DIR"
}
trap cleanup EXIT

restore_backup() {
    echo "ERROR: sync failed. Restoring previous policy files from backup." >&2
    for file in "${POLICY_FILES[@]}"; do
        if [ -f "$BACKUP_DIR/$file" ]; then
            cp "$BACKUP_DIR/$file" "$MODULE_ROOT/$file"
        fi
    done
    exit 1
}

# Sanity check: make sure we're in a module repo
if [ ! -f "$MODULE_ROOT/CLAUDE.md" ]; then
    echo "ERROR: $MODULE_ROOT does not contain CLAUDE.md." >&2
    echo "       This script must be run from inside a module repo." >&2
    exit 1
fi

echo "Module: $MODULE_ROOT"

# Backup existing copies
mkdir -p "$BACKUP_DIR"
for file in "${POLICY_FILES[@]}"; do
    if [ -f "$MODULE_ROOT/$file" ]; then
        cp "$MODULE_ROOT/$file" "$BACKUP_DIR/$file"
    fi
done

# Pull policy
if [ "$USE_LOCAL" = "true" ]; then
    if [ ! -d "$LOCAL_MIRROR" ]; then
        echo "ERROR: --from-local specified but $LOCAL_MIRROR does not exist." >&2
        restore_backup
    fi
    echo "Pulling policy from local mirror: $LOCAL_MIRROR"
    cp -r "$LOCAL_MIRROR/." "$TEMP_DIR/" || restore_backup
else
    echo "Pulling policy from $POLICY_REPO"
    git clone --depth 1 --quiet "$POLICY_REPO" "$TEMP_DIR" || restore_backup
fi

# Copy new versions
missing=()
for file in "${POLICY_FILES[@]}"; do
    src="$TEMP_DIR/$file"
    dst="$MODULE_ROOT/$file"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "  Updated: $file"
    else
        missing+=("$file")
        echo "  WARNING: missing in policy source: $file" >&2
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "WARNING: ${#missing[@]} policy file(s) missing in source." >&2
    echo "         Existing vendored copies (if any) were preserved." >&2
fi

echo "Sync complete."
