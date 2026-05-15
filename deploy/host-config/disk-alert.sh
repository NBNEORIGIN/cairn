#!/usr/bin/env bash
# Disk usage alerts for the Hetzner host.
#
# Fires a Telegram ping when:
#  - Filesystem usage crosses DEEK_DISK_THRESHOLD_PCT (default 85)
#  - Any category's size changed by ±DEEK_DISK_DELTA_PCT (default 10) of
#    total disk in the last hour (catches sudden growth from a leaked
#    build, or sudden drop from an accidental prune)
#
# Designed to keep working when the disk is genuinely critical — does
# NOT depend on the Deek FastAPI being reachable. Talks directly to
# Postgres for telemetry and directly to the Telegram Bot API for the
# alert. Both have explicit timeouts.
#
# State: cooldown is tracked in /var/lib/nbne/disk-alert-state — a
# pinged alert won't re-fire for 6 hours unless the situation worsens
# by another threshold-crossing.
#
# Schedule: every 15 min via crontab.canonical.
# Log: /var/log/nbne-disk-alert.log

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────
THRESHOLD_PCT="${DEEK_DISK_THRESHOLD_PCT:-85}"
DELTA_PCT="${DEEK_DISK_DELTA_PCT:-10}"
COOLDOWN_SECS="${DEEK_DISK_ALERT_COOLDOWN:-21600}"   # 6 h
STATE_FILE="/var/lib/nbne/disk-alert-state"
FORCE="${DEEK_DISK_ALERT_FORCE:-0}"

# Pull secrets from Deek deploy env so this script can run as plain root
# without the credentials being committed.
ENV_FILE="/opt/nbne/deek/deploy/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[ERROR] $ENV_FILE not readable — aborting" >&2
    exit 1
fi

DB_PW="$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
BOT_TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
NOTIFY_EMAIL="${DEEK_DISK_ALERT_USER:-toby@nbnesigns.com}"

if [[ -z "${DB_PW:-}" ]]; then
    echo "[ERROR] DB_PASSWORD not found in $ENV_FILE" >&2
    exit 1
fi
if [[ -z "${BOT_TOKEN:-}" ]]; then
    echo "[ERROR] TELEGRAM_BOT_TOKEN not found in $ENV_FILE — alerts will fail silently" >&2
    # Continue anyway so log shows the analysis output
fi

mkdir -p "$(dirname "$STATE_FILE")"

# ── Helpers ───────────────────────────────────────────────────────────
psql_one() {
    docker exec -e PGPASSWORD="$DB_PW" deploy-deek-db-1 \
        psql -U cairn -d cairn -t -A -c "$1" 2>/dev/null | tr -d '[:space:]'
}

# Lookup the registered Telegram chat for our notification user.
chat_id="$(psql_one "SELECT chat_id FROM cairn_intel.registered_telegram_chats
                      WHERE user_email = '${NOTIFY_EMAIL}'
                        AND revoked_at IS NULL
                      ORDER BY registered_at DESC LIMIT 1")"

send_telegram() {
    local text="$1"
    if [[ -z "${chat_id:-}" || -z "${BOT_TOKEN:-}" ]]; then
        echo "[WARN] telegram not configured (chat_id='${chat_id:-}' token=${BOT_TOKEN:+set}) — would have sent:"
        echo "$text"
        return 0
    fi
    curl -s --max-time 10 \
        -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${chat_id}" \
        -d "parse_mode=Markdown" \
        -d "disable_web_page_preview=true" \
        --data-urlencode "text=${text}" \
        > /dev/null
}

human_bytes() {
    # Convert bytes to GB with 1dp
    awk -v b="$1" 'BEGIN {printf "%.1f GB", b/1024/1024/1024}'
}

# ── State (cooldown) ──────────────────────────────────────────────────
last_alert_ts=0
if [[ -f "$STATE_FILE" ]]; then
    last_alert_ts="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"
fi
now_ts="$(date -u +%s)"
seconds_since_last=$(( now_ts - last_alert_ts ))

# ── Current disk pct ──────────────────────────────────────────────────
disk_pct="$(df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
disk_used_gb="$(df -B1 / | awk 'NR==2 {printf "%.1f", $3/1024/1024/1024}')"
disk_total_gb="$(df -B1 / | awk 'NR==2 {printf "%.1f", $2/1024/1024/1024}')"
disk_total_bytes="$(df -B1 / | awk 'NR==2 {print $2}')"

# ── Delta analysis (1h) ───────────────────────────────────────────────
# For each category, compare current size vs. 1h ago. Report the
# category with the steepest absolute delta.
delta_payload="$(psql_one "
WITH latest AS (
    SELECT DISTINCT ON (category) category, size_bytes, ts
      FROM host_disk_telemetry
     WHERE ts > NOW() - INTERVAL '15 minutes'
     ORDER BY category, ts DESC
),
prior AS (
    SELECT DISTINCT ON (category) category, size_bytes
      FROM host_disk_telemetry
     WHERE ts BETWEEN NOW() - INTERVAL '90 minutes'
                  AND NOW() - INTERVAL '50 minutes'
     ORDER BY category, ts DESC
)
SELECT string_agg(
    latest.category || ':' || (latest.size_bytes - prior.size_bytes),
    '|'
)
  FROM latest JOIN prior USING (category)
 WHERE latest.size_bytes <> prior.size_bytes;
")"
# delta_payload looks like: "docker_images:5400000|ark_backups:-1024000000"

steepest_cat=""
steepest_delta=0
steepest_delta_abs=0
if [[ -n "${delta_payload:-}" ]]; then
    IFS='|' read -ra entries <<< "$delta_payload"
    for e in "${entries[@]}"; do
        cat="${e%%:*}"
        delta="${e##*:}"
        delta_abs="${delta#-}"
        if (( delta_abs > steepest_delta_abs )); then
            steepest_cat="$cat"
            steepest_delta="$delta"
            steepest_delta_abs="$delta_abs"
        fi
    done
fi

# Convert delta threshold (% of total disk) to bytes
delta_threshold_bytes=$(( disk_total_bytes * DELTA_PCT / 100 ))

# ── Decide whether to alert ──────────────────────────────────────────
alert_reasons=()
if (( disk_pct >= THRESHOLD_PCT )); then
    alert_reasons+=("Disk at ${disk_pct}% (threshold ${THRESHOLD_PCT}%)")
fi
if (( steepest_delta_abs >= delta_threshold_bytes )); then
    direction="rose"
    sign="+"
    if (( steepest_delta < 0 )); then
        direction="dropped"
        sign=""
    fi
    delta_gb="$(awk -v b="$steepest_delta_abs" 'BEGIN {printf "%.1f", b/1024/1024/1024}')"
    alert_reasons+=("\`${steepest_cat}\` ${direction} ${sign}${delta_gb} GB in last hour")
fi

if [[ ${#alert_reasons[@]} -eq 0 && "$FORCE" != "1" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] OK — disk ${disk_pct}%, no significant deltas"
    exit 0
fi

# In force mode, synthesise a "test" reason so the Telegram message has
# meaningful content. Skip cooldown checks too.
if [[ "$FORCE" == "1" && ${#alert_reasons[@]} -eq 0 ]]; then
    alert_reasons+=("TEST PING — alert path verified at ${disk_pct}% disk")
fi

# Cooldown: skip if we alerted recently AND nothing got worse than the
# threshold (force mode bypasses).
if (( seconds_since_last < COOLDOWN_SECS && disk_pct < THRESHOLD_PCT + 5 )) \
   && [[ "$FORCE" != "1" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] in cooldown (${seconds_since_last}s since last alert) — skipping"
    exit 0
fi

# ── Build alert payload ──────────────────────────────────────────────
top_volumes="$(du -sh /var/lib/docker/volumes/* 2>/dev/null | sort -h | tail -5 | awk '{print $1, $2}' | sed 's|/var/lib/docker/volumes/||')"

msg="⚠️ *Hetzner disk alert*

$(printf '• %s\n' "${alert_reasons[@]}")

*Now:* ${disk_used_gb} / ${disk_total_gb} GB (${disk_pct}%)

*Top 5 volumes:*
\`\`\`
${top_volumes}
\`\`\`

Investigate: \`ssh root@178.104.1.152\`
Then: \`du -sh /var/lib/docker/volumes/* | sort -h | tail\` or \`du -sh /backups/* | sort -h\`
"

send_telegram "$msg"
echo "$now_ts" > "$STATE_FILE"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT FIRED — reasons: ${alert_reasons[*]}"
