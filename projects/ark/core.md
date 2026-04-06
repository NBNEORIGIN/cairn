# Phloe Ark — core.md

## Purpose

Ensure that if the Hetzner production server (178.104.1.152) is completely destroyed,
every Phloe client site can be restored to a known recent state (< 24 hours data loss)
on a fresh server within hours, not days. Zero client data loss is the goal;
< 24 hours is the minimum acceptable standard.

## Infrastructure Context

**Critical:** Phloe runs in Docker. Every tenant is a separate Docker Compose stack.
This has direct implications for backup mechanics:

- Databases are NOT accessible as a system Postgres user. Each tenant's database runs
  inside its own container: `<slug>-db-1`. pg_dump must be run via `docker exec`:
  ```bash
  docker exec <slug>-db-1 pg_dump -U nbne -d <slug> | gzip > <slug>_YYYY-MM-DD.sql.gz
  ```
- Database names are the tenant slug directly — NOT prefixed with `phloe_`.
  e.g. `demnurse`, `northumberland-karate`, `amble-pincushion`
- Media files are in Docker named volumes (`<slug>_media`), not filesystem paths like
  `/var/www/*/media/`. Extract via:
  ```bash
  docker run --rm -v <slug>_media:/data -v /backups/ark:/out alpine \
    tar czf /out/<slug>_media_YYYY-MM-DD.tar.gz -C /data .
  ```
- Environment files: `/opt/nbne/instances/<slug>/.env` — back these up (encrypted).
  They contain Stripe keys, email credentials, DB passwords. Never push these to B2 unencrypted.
- Compose file: `/opt/nbne/shared/docker/docker-compose.client.yml` (shared)
  Override per tenant (where present): `/opt/nbne/instances/<slug>/docker-compose.production.yml`
- Tenant discovery: enumerate `/opt/nbne/instances/` — each subdirectory is a tenant slug.
  Do NOT hardcode the tenant list. Discover dynamically.

## Architecture Overview

### Layer 1: Automated Daily Backup

A cron job (systemd timer acceptable) on the Hetzner production server running daily
at 03:00 UTC:

#### Per tenant (iterate `/opt/nbne/instances/`):
1. `docker exec <slug>-db-1 pg_dump -U nbne -d <slug>` → compressed SQL
2. Docker volume dump of `<slug>_media` → compressed tar
3. Copy of `/opt/nbne/instances/<slug>/.env` → encrypted copy
4. Bundle into a single archive per tenant: `<slug>_YYYY-MM-DD.tar.gz`

#### Platform-level:
5. Backup of nginx configs (`/etc/nginx/sites-available/`)
6. Backup of SSL certificates — Let's Encrypt at `/etc/letsencrypt/`, Cloudflare origin
   certs at `/etc/ssl/cloudflare/`
7. Git commit hash of each deployed repo (production and shared):
   - `/opt/nbne/production` → `git rev-parse HEAD`
   - `/opt/nbne/shared` → `git rev-parse HEAD`
8. Manifest file: `manifest.json` with timestamp, tenant list, row counts, git hashes

#### Encryption:
- Use `age` (https://github.com/FiloSottile/age) — simpler than GPG
- Encrypt `.env` files before they leave the server
- Full archive encryption in Phase 5 — Phase 1 uses local-only unencrypted dumps
  (better than nothing; encryption added in Phase 5 before off-site push)

#### Off-site storage (Phase 2+):
- Primary: Backblaze B2 (provider isolation from Hetzner)
- Secondary (optional): Hetzner Storage Box (BX11 €3.81/month, fast restore)
- Upload via `rclone` (supports both natively)

#### Retention policy:
- 7 daily, 4 weekly (Sunday), 3 monthly (1st of month)
- Pruning via rclone or a simple date-comparison script

#### Monitoring:
- On success: append to `/var/log/ark-backup.log`
- On failure: email to `toby@nbnesigns.com` (use msmtp or mailutils — check availability)
- Health check cron: verify most recent backup exists and is < 26 hours old

---

### Layer 2: Human-Readable CSV Export

Daily CSV export per tenant (Phase 4):
- Bookings, Customers, Products/Services, Staff, Configuration summary
- One directory per tenant, one CSV per table, plus `manifest.json`
- Purpose: GDPR break-glass, manual reconstruction if SQL dumps fail

---

### Layer 3: Re-Provisioning Script (The Ark Script)

Single script (Phase 3):
```bash
./ark-restore.sh --backup /path/to/backup/2026-03-30/ --server <fresh-ip>
```

Sequence:
1. Install stack: Docker, nginx, certbot, rclone on fresh Ubuntu 24
2. Clone production repo at recorded git hash
3. Per tenant: recreate Docker stack, restore DB via `docker exec psql`, restore media volume
4. Restore nginx configs and SSL certificates
5. Restore `.env` files (decrypt with age key)
6. Cloudflare API: update A records for all tenant domains to new server IP
7. Verify: `curl -I https://<domain>` → expect 200
8. Install and verify first backup run on new server

---

### Layer 4: Recovery Drills

- Monthly: restore one random tenant to a test server — verify it works, log result
- Quarterly: full disaster simulation — all tenants, fresh server, target < 4 hours

---

## Current Tenant Inventory

Discovered dynamically from `/opt/nbne/instances/` — do NOT hardcode this list.
Reference only — update as tenants change.

| Slug | Domain | DB name | Paradigm | Status |
|------|--------|---------|----------|--------|
| demnurse | demnurse.nbne.uk | demnurse | appointment | live client |
| northumberland-karate | northumberland-karate.phloe.co.uk | northumberland-karate | class | live client |
| amble-pincushion | amble-pincushion.phloe.co.uk | amble-pincushion | class | demo/prospect |
| pizza-shack-x | pizza-shack-x.nbne.uk | pizza-shack-x | food | demo |
| salon-x | salon-x.nbne.uk | salon-x | appointment | demo |
| restaurant-x | restaurant-x.nbne.uk | restaurant-x | table | demo |
| health-club-x | health-club-x.nbne.uk | health-club-x | class | demo |
| mind-department | mind-department.nbne.uk | mind-department | appointment | demo/prospect |
| nbne | nbne.nbne.uk | nbne | — | internal |

---

## Implementation Priority

### Phase 1 — Basic Protection ✅ COMPLETE (2026-03-31)
- [x] Enumerate all tenant containers and DB names from live server
- [x] Write `/opt/ark/backup.sh` — Docker-aware pg_dump + volume media dump
- [x] Local backup destination: `/backups/ark/daily/<slug>/<date>/`
- [x] Cron: `30 3 * * * /opt/ark/backup.sh` (03:30 UTC — staggered from legacy script at 03:00)
- [x] Email alert on failure (sendmail / postfix)
- [x] Manual test run — 9/9 tenants backed up, 0 failures, ~40 seconds

**First backup results (2026-03-31):**
- demnurse: 87KB SQL, 33.6MB media
- northumberland-karate: 58KB SQL, 2.1MB media
- amble-pincushion: 49KB SQL, 87B media
- mind-department: 123KB SQL, 9KB media
- pizza-shack-x: 6.6MB SQL, 2.6MB media
- salon-x: 3.1MB SQL, 11KB media
- nbne (internal): 4.1MB SQL, 562MB media
- restaurant-x: 3.1MB SQL, 84B media
- health-club-x: 3.1MB SQL, 10KB media

**Note:** Legacy backup script at `/opt/nbne/scripts/backup.sh` still active (runs 03:00 UTC,
SQL dumps only, 30-day pruning). Superseded by Ark but left running until Phase 2 is stable.
Ark cron staggered to 03:30 to avoid concurrent pg_dump contention. Retire legacy script
when Phase 2 (B2 off-site) is confirmed working.

### Phase 2 — Off-Site Push ✅ COMPLETE (2026-03-31)
- [x] Toby creates Contabo Object Storage account and bucket (ark-backups, EU Germany)
- [x] Install rclone v1.73.3 on server
- [x] Configure rclone with Contabo S3-compatible endpoint (eu2.contabostorage.com)
- [x] Push daily backups to Contabo after local dump — 620MB in 13 seconds (~46MB/s)
- [x] Verify: 31 files landed across 10 directories on Contabo, all tenants present
- [x] Retention pruning: 7 daily / 4 weekly / 3 monthly (Python, runs post-push)

**Provider**: Contabo Object Storage, EU Germany — German company, fixed €2.99/month,
no egress fees. Full GDPR-compliant data residency.
**Note**: Backblaze B2 was considered and rejected in favour of Contabo (EU-sovereign,
fixed pricing, no US company involvement).

### Phase 3 — Re-Provisioning Script ✅ COMPLETE (2026-03-31)
- [x] `ark-restore.sh` written and deployed to `/opt/ark/ark-restore.sh`
- [x] Cloudflare API DNS cutover — auto-discovers zones, updates all tenant A records
- [x] Full restore sequence: deps → rclone → download → SSH keys → git clone → per-tenant stack → nginx → SSL → DNS → verify → cron
- [x] backup.sh updated: now also archives letsencrypt.tar.gz, cloudflare-certs.tar.gz, ssh-keys.tar.gz (chmod 600)
- [x] Test drill on fresh Hetzner CX23 — PASSED 2026-03-31
- [ ] Recovery runbook document

**Usage:**
```bash
ssh root@<new-server> "bash -s" < /opt/ark/ark-restore.sh -- \
  --date 2026-03-31 \
  --cf-token <cloudflare_api_token>
```
Or with `--dry-run` to validate without making changes.

**Cloudflare token requirement**: Must have Zone:Edit permissions across all NBNE zones
(nbne.uk, phloe.co.uk, ganbarukai.co.uk, nbnesigns.co.uk). Confirm token scope before
a real restore — the nbne tenant's CLOUDFLARE_API_TOKEN may be zone-scoped only.

### Phase 4 — CSV Export + Monitoring (2–3 weeks)
- [ ] Django management command: `export_tenant_csv`
- [ ] Manifest generation
- [ ] Backup health dashboard or status page

### Phase 5 — Encryption + Hardening (3–4 weeks)
- [ ] `age` encryption for all archives before off-site push
- [ ] Key management documentation (Toby holds key locally + sealed emergency copy)
- [ ] Retention policy automation
- [ ] Quarterly full-disaster drill schedule

---

## Off-Site Storage Costs

| Provider | Cost | Notes |
|----------|------|-------|
| Backblaze B2 | ~$0.006/GB/month | Primary — provider-isolated from Hetzner |
| Hetzner Storage Box BX11 | €3.81/month, 1TB | Fast restore, same-provider convenience |
| Estimated for current tenants | < $2/month | Scales with media volume |

---

## Decision Log

### 2026-03-31 — Project Registered
**Context**: Phloe has zero backup or disaster recovery infrastructure. If the Hetzner
server at 178.104.1.152 fails, all client data and all tenant sites are permanently
lost. DemNurse and Ganbarukai are live paying clients. This is an unacceptable
business risk.
**Decision**: Create "Ark" — phased backup, recovery, and re-provisioning system.
Phase 1 (pg_dump + cron, Docker-aware) implemented this week. Phase 2–5 follow.
**Rationale**: Disaster recovery is infrastructure, not a feature. The cost of
implementation (days) is trivial vs the cost of data loss (business-ending).
**Rejected**: Managed snapshots (insufficient granularity, no tenant-level restore),
manual backups (will be forgotten), deferral (every day unprotected is uninsured risk).
**Key architectural constraint identified at registration**: Phloe is fully Dockerised.
Backup script must use `docker exec <slug>-db-1 pg_dump` and Docker volume extraction,
not system-level postgres or filesystem media paths. DB names = slug, not phloe_<slug>.

### 2026-03-31 — Phase 1 Complete
**Context**: backup.sh written, safety-reviewed, deployed to `/opt/ark/backup.sh`,
manual test run succeeded 9/9 tenants, 0 failures, ~40 seconds total.
**Decision**: Cron installed at 03:30 UTC (not 03:00 — staggered from legacy script
at `/opt/nbne/scripts/backup.sh` which does SQL-only dumps at 03:00). Legacy script
left active until Phase 2 is proven; it provides the only pruning currently (30 days).
**Outcome**: Production server now has daily automated backups of all tenant SQL,
media volumes, and `.env` files. `.env.bak` files are chmod 600. Manifest JSON
written per run. Failure email via postfix/sendmail to toby@nbnesigns.com.
**Next**: Phase 2 — Toby to create Backblaze B2 account and bucket; then install
rclone and implement off-site push.

### 2026-03-31 — Phase 2 Complete (Off-Site Push)
**Context**: Phase 1 left backups local-only on the same server that could fail.
Provider selection: Backblaze B2 EU considered, rejected in favour of Contabo Object
Storage — German company, fixed €2.99/month for 250GB, no egress fees, full EU data
residency. Bucket: `ark-backups` at `eu2.contabostorage.com`.
**Decision**: rclone configured with Contabo S3-compatible endpoint. backup.sh updated
to push today's backup after local dump, with Python-based retention pruning (7 daily,
4 weekly, 3 monthly). First full push: 620MB, 31 files, 13 seconds (~46MB/s).
**Outcome**: Every nightly backup is now written locally AND pushed off-site to Contabo
before the script exits. A single Hetzner failure no longer means data loss.
**Next**: Phase 3 — re-provisioning script (`ark-restore.sh`).

### 2026-03-31 — Phase 3 Complete (Re-Provisioning Script)
**Context**: backup.sh was missing SSL certs and SSH deploy keys, making a true
bare-metal restore impossible. ark-restore.sh needed the full picture of the server
infrastructure before it could be written correctly.
**Decision**: Extended backup.sh platform section to archive letsencrypt.tar.gz,
cloudflare-certs.tar.gz (both SSL patterns in use), and ssh-keys.tar.gz (chmod 600,
needed for git clone of production/shared repos). Wrote ark-restore.sh (~350 lines):
accepts `--date` and `--cf-token`, runs on fresh Ubuntu 24, installs all deps, pulls
backup from Contabo, restores per-tenant stack (env → docker → db → media), restores
nginx + SSL, updates Cloudflare DNS via API, verifies all tenants HTTP 200/301, installs
ark cron. Dry-run mode available.
**Outstanding**: Test drill on fresh Hetzner CX22 — do not claim Phase 3 truly complete
until a real restore has been verified end-to-end.
**Cloudflare caveat**: The CF API token in nbne/.env may be zone-scoped. Confirm it
covers all four NBNE zones before a real drill.

### 2026-03-31 — Phase 3 Drill: PASSED
**Server**: Hetzner CX23, Nuremberg, Ubuntu 24.04 (159.69.42.156, deleted post-drill)
**Result**: All 9 Docker stacks built and started. All 27 containers healthy.
DemNurse: 17 bookings confirmed in DB. Ganbarukai: 52 bookings confirmed in DB.
nginx restored, all 9 sites enabled, config test passed. Let's Encrypt + Cloudflare
certs restored. Ark cron installed. Total time: ~40 minutes.
**Bugs found and fixed during drill**:
1. nbne_platform main branch has broken app/book/page.tsx — restore now clones
   nbne_production to both /opt/nbne/production AND /opt/nbne/shared (matches
   production server reality where both dirs track production commits).
2. Verify step was hitting /api/health/ (404) instead of frontend root / (200) —
   fixed to curl frontend port with Host header.
**Real disaster time estimate**: ~30 minutes from server loss to all clients live,
assuming Hetzner provisioning (~2min) + restore script (~25min) + DNS propagation.
