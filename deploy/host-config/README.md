# Deek — Hetzner Host Configuration

Canonical, version-controlled source for everything that runs **on the
Hetzner host itself** (outside any container): crontab, maintenance
scripts, logrotate rules, alert scripts.

**Why this exists**

Before 2026-05-15 the host's crontab and `/opt/nbne/scripts/` lived
nowhere in git. A disk-fill outage that morning made the gap visible:
no way to audit history, no way to review changes, no way to redeploy
the host config to a recovery box. This directory closes that gap.

## What's in here

| File | Deploys to | Purpose |
|---|---|---|
| `crontab.canonical` | `crontab -e` (root) | The full canonical root crontab. `sync-to-host.sh` rewrites the live crontab from this file. |
| `prune-daily.sh` | `/opt/nbne/scripts/prune-daily.sh` | Daily Docker builder-cache prune with `--reserved-space 2GB` warm-cache protection. |
| `prune-weekly.sh` | `/opt/nbne/scripts/prune-weekly.sh` | Weekly Docker image prune for orphaned-image cleanup (filter `until=72h`). |
| `disk-telemetry.sh` | `/opt/nbne/scripts/disk-telemetry.sh` | Hourly: snapshot `docker system df` and `df /` into the `host_disk_telemetry` table. |
| `disk-alert.sh` | `/opt/nbne/scripts/disk-alert.sh` | Every 15 min: alert on threshold (>85%) or bidirectional delta (±10% in 1h). Routes via existing Telegram bot. |
| `logrotate.d-nbne-custom` | `/etc/logrotate.d/nbne-custom` | Rotate `/var/log/cairn-*.log` and `/var/log/deek-*.log` (custom log files outside Debian's default rules). |
| `sync-to-host.sh` | Run locally on dev box | Push everything in this directory to Hetzner via SSH + rsync. Idempotent. |

## Deploying

From a Deek dev box with SSH access to Hetzner:

```bash
cd D:/claw/deploy/host-config
bash sync-to-host.sh
```

`sync-to-host.sh` will:

1. `rsync` scripts to `/opt/nbne/scripts/` (preserves +x bit)
2. Install `logrotate.d-nbne-custom` to `/etc/logrotate.d/nbne-custom`
3. Install `crontab.canonical` to root's crontab (after diffing first; aborts on suspicious diff)
4. Verify `logrotate -d /etc/logrotate.d/nbne-custom` parses cleanly
5. Verify `crontab -l | head` matches what we just wrote

## Manual checks

```bash
# Disk usage right now
ssh root@178.104.1.152 'df -h /'

# Last few telemetry rows
docker exec deploy-deek-db-1 psql -U cairn -d cairn -c \
  "SELECT * FROM host_disk_telemetry ORDER BY ts DESC LIMIT 8;"

# Confirm alert path works (forces a Telegram ping)
ssh root@178.104.1.152 'DEEK_DISK_ALERT_FORCE=1 /opt/nbne/scripts/disk-alert.sh'

# Confirm logrotate rules pass dry-run
ssh root@178.104.1.152 'logrotate -d /etc/logrotate.d/nbne-custom 2>&1 | head -30'
```

## Operating principles

- **No host change leaves this directory.** If you find yourself editing
  `/etc/cron.d/*` or `/opt/nbne/scripts/foo.sh` on Hetzner directly,
  stop, move the change here, and re-sync. The host should be
  reproducible from this directory plus the application docker
  compose files.
- **Crontab is fully owned by `crontab.canonical`.** `sync-to-host.sh`
  overwrites the live crontab in full. If something needs to land
  outside Deek's purview, add it here and note the owning module.
- **All custom logs go through logrotate.** Adding a new cron entry
  that writes to `/var/log/...`? Make sure the file name matches the
  glob in `logrotate.d-nbne-custom` (`cairn-*.log` or `deek-*.log`),
  or add a new glob to it.
- **Alert recipient is whoever's registered in `cairn_intel.registered_telegram_chats`** for `toby@nbnesigns.com`. Same channel as the inbox-draft notifier.
