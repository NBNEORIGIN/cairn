#!/usr/bin/env bash
# Daily Docker builder-cache prune.
# Drops idle build cache while protecting the 2GB warm cache so the next
# morning's first deploy on each module doesn't have to re-fetch every
# layer cold.
#
# Schedule: 02:00 daily via crontab.canonical
# Log: /var/log/nbne-prune.log

set -euo pipefail

LOG_PREFIX="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] prune-daily"
echo "${LOG_PREFIX} start"

# Disk before
before_used="$(df -B1 / | awk 'NR==2 {print $3}')"

# Builder prune: keep 2GB of warm cache, drop the rest.
# Docker 25+ renamed --keep-storage to --reserved-space; --keep-storage
# is now deprecated but still works. We use the new flag if available
# (BuildKit 0.14+), falling back to the old one.
if docker builder prune --help 2>&1 | grep -q -- '--reserved-space'; then
    docker builder prune -af --reserved-space 2GB 2>&1 | tail -5
else
    docker builder prune -af --keep-storage 2GB 2>&1 | tail -5
fi

after_used="$(df -B1 / | awk 'NR==2 {print $3}')"
delta_mb=$(( (before_used - after_used) / 1024 / 1024 ))
disk_used_pct="$(df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"

echo "${LOG_PREFIX} done — reclaimed ${delta_mb} MB, disk now ${disk_used_pct}%"
