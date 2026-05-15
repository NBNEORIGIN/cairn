#!/usr/bin/env bash
# Hourly snapshot of host disk usage.
# Writes one row per category (filesystem, docker_images, docker_containers,
# docker_volumes, docker_build_cache, ark_backups) into host_disk_telemetry.
#
# disk-alert.sh reads this table to compute deltas and slopes — alerts
# only fire on real trends, not single-tick spikes.
#
# Schedule: hourly at :05 via crontab.canonical
# Log: /var/log/nbne-disk-telemetry.log

set -euo pipefail

# Compute current values
fs_used_bytes="$(df -B1 / | awk 'NR==2 {print $3}')"
fs_total_bytes="$(df -B1 / | awk 'NR==2 {print $2}')"

# docker system df produces "21.02GB" style strings; convert to bytes.
# Format we parse looks like:
#   TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
#   Images          51        51        21.02GB   21.02GB (100%)
to_bytes() {
    local s="$1"
    local n unit
    n="$(echo "$s" | sed -E 's/([0-9.]+).*/\1/')"
    unit="$(echo "$s" | sed -E 's/[0-9.]+([A-Za-z]+).*/\1/')"
    case "$unit" in
        kB|KB|K) printf '%.0f' "$(echo "$n * 1024" | bc)" ;;
        MB|M)    printf '%.0f' "$(echo "$n * 1024 * 1024" | bc)" ;;
        GB|G)    printf '%.0f' "$(echo "$n * 1024 * 1024 * 1024" | bc)" ;;
        TB|T)    printf '%.0f' "$(echo "$n * 1024 * 1024 * 1024 * 1024" | bc)" ;;
        B|"")    printf '%.0f' "$n" ;;
        *)       echo 0 ;;
    esac
}

# Parse docker system df output (skip header)
docker_output="$(docker system df 2>/dev/null | tail -n +2)"

images_bytes="$(echo "$docker_output" | awk '$1=="Images" {print $4}' | head -1)"
containers_bytes="$(echo "$docker_output" | awk '$1=="Containers" {print $4}' | head -1)"
volumes_bytes="$(echo "$docker_output" | awk '$1=="Local" && $2=="Volumes" {print $5}' | head -1)"
buildcache_bytes="$(echo "$docker_output" | awk '$1=="Build" && $2=="Cache" {print $5}' | head -1)"

images_bytes="$(to_bytes "${images_bytes:-0B}")"
containers_bytes="$(to_bytes "${containers_bytes:-0B}")"
volumes_bytes="$(to_bytes "${volumes_bytes:-0B}")"
buildcache_bytes="$(to_bytes "${buildcache_bytes:-0B}")"

# Ark backups (the disk hog that took out manufacture on 2026-05-15)
ark_bytes="$(du -sb /backups/ark 2>/dev/null | awk '{print $1}')"
ark_bytes="${ark_bytes:-0}"

# Write into deek DB via deek-api container.
# Single multi-row insert keeps the timestamp atomic across categories.
docker exec -e PGPASSWORD=cairn_nbne_2026 deploy-deek-db-1 \
    psql -U cairn -d cairn -v ON_ERROR_STOP=1 -c "
INSERT INTO host_disk_telemetry (ts, category, size_bytes) VALUES
    (NOW(), 'filesystem_used',     $fs_used_bytes),
    (NOW(), 'filesystem_total',    $fs_total_bytes),
    (NOW(), 'docker_images',       $images_bytes),
    (NOW(), 'docker_containers',   $containers_bytes),
    (NOW(), 'docker_volumes',      $volumes_bytes),
    (NOW(), 'docker_build_cache',  $buildcache_bytes),
    (NOW(), 'ark_backups',         $ark_bytes);
" > /dev/null

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] disk-telemetry — fs=${fs_used_bytes}B images=${images_bytes}B vols=${volumes_bytes}B cache=${buildcache_bytes}B ark=${ark_bytes}B"
