#!/usr/bin/env bash
# Sync deek/deploy/host-config/ → Hetzner host.
#
# What it does:
#   1. rsync prune/disk scripts to /opt/nbne/scripts/
#   2. Install logrotate config to /etc/logrotate.d/nbne-custom
#   3. Diff canonical crontab vs live crontab; abort if suspicious
#   4. Install canonical crontab to root's crontab
#   5. Apply host_disk_telemetry schema if missing
#   6. Verify each step
#
# Idempotent — safe to run repeatedly.
#
# Usage:
#   bash deploy/host-config/sync-to-host.sh                  # interactive
#   bash deploy/host-config/sync-to-host.sh --force          # skip prompts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_HOST="root@178.104.1.152"
SSH_KEY="${HOME}/.ssh/id_ed25519"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no"
FORCE="${1:-}"

ssh_run() {
    ssh $SSH_OPTS "$SSH_HOST" "$@"
}

scp_file() {
    scp $SSH_OPTS "$1" "${SSH_HOST}:$2"
}

confirm() {
    if [[ "$FORCE" == "--force" ]]; then
        return 0
    fi
    read -r -p "$1 [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

echo "═══ sync-to-host.sh ═══"
echo "Source: $SCRIPT_DIR"
echo "Target: $SSH_HOST"
echo

# ── 1. Maintenance scripts ───────────────────────────────────────────
echo "── 1. Maintenance scripts → /opt/nbne/scripts/"
ssh_run "mkdir -p /opt/nbne/scripts /var/lib/nbne"
for f in prune-daily.sh prune-weekly.sh disk-telemetry.sh disk-alert.sh; do
    scp_file "${SCRIPT_DIR}/${f}" "/opt/nbne/scripts/${f}"
    ssh_run "chmod +x /opt/nbne/scripts/${f}"
    echo "  ✓ ${f}"
done

# ── 2. Logrotate config ──────────────────────────────────────────────
echo "── 2. Logrotate → /etc/logrotate.d/nbne-custom"
scp_file "${SCRIPT_DIR}/logrotate.d-nbne-custom" "/etc/logrotate.d/nbne-custom"
ssh_run "chmod 644 /etc/logrotate.d/nbne-custom && chown root:root /etc/logrotate.d/nbne-custom"
echo "── verifying logrotate parse:"
logrotate_errors="$(ssh_run "logrotate -d /etc/logrotate.d/nbne-custom 2>&1" | grep -iE '^error:|reading config.*failed|invalid option' | head -5 || true)"
if [[ -n "$logrotate_errors" ]]; then
    echo "[ERROR] logrotate config rejected:" >&2
    echo "$logrotate_errors" >&2
    exit 1
fi
echo "  ✓ logrotate parses cleanly"

# ── 3. host_disk_telemetry schema ────────────────────────────────────
echo "── 3. host_disk_telemetry schema"
scp_file "${SCRIPT_DIR}/disk-telemetry.schema.sql" "/tmp/disk-telemetry.schema.sql"
ssh_run "docker cp /tmp/disk-telemetry.schema.sql deploy-deek-db-1:/tmp/disk-telemetry.schema.sql"
ssh_run "docker exec -e PGPASSWORD=\$(grep '^DB_PASSWORD=' /opt/nbne/deek/deploy/.env | cut -d= -f2-) deploy-deek-db-1 psql -U cairn -d cairn -f /tmp/disk-telemetry.schema.sql" >/dev/null
echo "  ✓ schema applied (idempotent)"

# ── 4. Crontab diff & install ────────────────────────────────────────
echo "── 4. Crontab"
ssh_run "crontab -l 2>/dev/null > /tmp/crontab.live" || true
scp_file "${SCRIPT_DIR}/crontab.canonical" "/tmp/crontab.canonical"
echo "── diff (live → canonical, : means line will disappear; +/- means changed):"
ssh_run "diff --unified=1 /tmp/crontab.live /tmp/crontab.canonical | head -80" || true

# Safety: refuse to remove more than 5 cron entries without --force.
# Removing a single entry is fine; mass-removal indicates a misconfig.
removed_count="$(ssh_run "diff /tmp/crontab.live /tmp/crontab.canonical | grep -cE '^<' || true")"
if (( removed_count > 5 )) && [[ "$FORCE" != "--force" ]]; then
    echo
    echo "[ABORT] Canonical crontab would remove ${removed_count} live entries."
    echo "        Re-run with --force if this is intentional, or update"
    echo "        crontab.canonical to preserve the missing lines."
    exit 1
fi

if ! confirm "Install canonical crontab?"; then
    echo "Skipped crontab install"
else
    ssh_run "crontab /tmp/crontab.canonical"
    echo "  ✓ crontab installed"
fi

# ── 5. Smoke test scripts ────────────────────────────────────────────
echo "── 5. Smoke tests"
echo "── disk-telemetry.sh (1 row should land):"
ssh_run "/opt/nbne/scripts/disk-telemetry.sh 2>&1 | tail -3"
echo "── disk-alert.sh (dry — should report OK or alert):"
ssh_run "/opt/nbne/scripts/disk-alert.sh 2>&1 | tail -5"

echo
echo "═══ sync-to-host.sh: done ═══"
echo "Verify:"
echo "  ssh ${SSH_HOST} 'crontab -l | head -20'"
echo "  ssh ${SSH_HOST} 'tail /var/log/nbne-disk-telemetry.log'"
