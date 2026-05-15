#!/usr/bin/env bash
# Weekly Docker image prune.
# Removes images that have ZERO container references AND are older than
# 72 hours. Strictly safer than `docker image prune -a` alone because
# the until=72h filter protects images of containers that were stopped
# for a short maintenance window.
#
# Schedule: Monday 02:30 via crontab.canonical
# Log: /var/log/nbne-prune.log
#
# NEVER pass --volumes. Volumes contain every Postgres database on
# the host. Docker volume prune is a footgun, not a maintenance tool.

set -euo pipefail

LOG_PREFIX="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] prune-weekly"
echo "${LOG_PREFIX} start"

before_used="$(df -B1 / | awk 'NR==2 {print $3}')"

docker image prune -af --filter "until=72h" 2>&1 | tail -3

after_used="$(df -B1 / | awk 'NR==2 {print $3}')"
delta_mb=$(( (before_used - after_used) / 1024 / 1024 ))
disk_used_pct="$(df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"

echo "${LOG_PREFIX} done — reclaimed ${delta_mb} MB, disk now ${disk_used_pct}%"
