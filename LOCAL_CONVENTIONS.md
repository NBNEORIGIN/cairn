# LOCAL_CONVENTIONS.md
# NBNE — Canonical Paths, Project Keys, and Naming
# This is the single source of truth for conventions across all NBNE repos.
# Every CLAUDE.md references this file. Treat it as authoritative.
# Source of truth: github.com/NBNEORIGIN/nbne-policy
# Last updated: 16 April 2026

---

## Purpose

This file exists because the previous arrangement — conventions implied by
multiple overlapping documents (CLAUDE.md, DEEK_PROTOCOL.md,
DEEK_MODULES.md) — produced inconsistencies between intent and reality.
A fresh Claude Code session must be able to read this one file and know,
without ambiguity, where things live and what they are called.

If a brief or instruction contradicts this file, this file wins. The
contradicting brief is wrong and must be reconciled before work proceeds.

---

## Project Keys (canonical)

The short identifier used in every config, env var, log prefix, and path.
Pick a project key for a new project and never change it casually.

| Key | Long name | Status | Notes |
|---|---|---|---|
| `deek` | Central brain (formerly cairn, formerly deek) | Active | Rename in progress; aliases below |
| `cairn` | — | Alias for `deek` | Accepted during rename window; remove after Phase 3 |
| `deek` | — | Alias for `deek` | Legacy; remove on next pass |
| `manufacture` | Manufacture app | Active | |
| `phloe` | Phloe WaaS booking platform | Active | |
| `render` | Render product publishing app | Active | |
| `ledger` | Ledger financial management | Active | |
| `crm` | CRM v2 | Active | |
| `ami` | Amazon Intelligence (AMI) module | Active | Embedded inside Deek repo by design |
| `beacon` | Phloe Google Ads / closed-loop attribution | In development | |

**Rule:** project keys are lowercase, no underscores, no hyphens. They are
the same string in: env file paths, container names, database names, repo
names, log prefixes, and Deek `project=` parameters.

---

## Repository Layout

### Hetzner production (`178.104.1.152`)

```
/opt/nbne/<key>/                      Repo root for each module
/opt/nbne/<key>/.env                  Module env file (symlinked into docker/)
/opt/nbne/<key>/docker/                Docker compose directory
/opt/nbne/<key>/docker/docker-compose.yml
```

SSH: `ssh root@178.104.1.152 -i ~/.ssh/id_ed25519` (port 22)

**Decided:** `root` is the SSH user for production access. No deploy user
migration planned at this time.

**Exception — CRM:** currently at `/opt/nbne/client-sites/crm/` (predates
convention). Migrate to `/opt/nbne/crm/` when next doing CRM infrastructure
work.

### Windows dev box (Toby's PC)

```
D:\<key>\                              Canonical local repo path per module
```

**Decided:** Phloe will migrate from `D:\nbne_business\nbne_platform` to
`D:\phloe\`. Until the migration is done, both paths are accepted, but
`D:\phloe\` is the target. The migration is a simple `git clone` to the
new path — no code changes needed, just update any IDE workspace configs
and CC session launch paths.

---

## URL Pattern

```
https://<key>.nbnesigns.co.uk          Public URL for each module
```

Examples: `manufacture.nbnesigns.co.uk`, `phloe.nbnesigns.co.uk`,
`deek.nbnesigns.co.uk` (post-rename), `deek.nbnesigns.co.uk` (legacy alias
during rename window).

---

## Port Allocation

**Decided:** standardise on actual production ports. The original
DEEK_MODULES.md allocation was aspirational and production diverged.
The canonical port map going forward is based on production reality:

| Module | Backend | Frontend | Notes |
|---|---|---|---|
| Deek (Deek) API | 8765 | 3020 | Brain — never moves |
| Manufacture | 8015 | 3015 | Production reality |
| Render | 8025 | — | Flask, single port |
| CRM | 3023 | — | Next.js via PM2, single port |
| Ledger | 8001 | 3001 | Production compose |
| Phloe (per tenant) | 80xx | 30xx | e.g. mind-department: 8010/3010 |
| Beacon | 8017 | 3017 | Dev only (no production yet) |

**Rule:** when provisioning a new module, pick the next available port
pair that doesn't collide. Document it here before deploying.

---

## Database Conventions

```
DB name:     <key>            (e.g. manufacture, phloe, deek)
DB user:     nbne             (canonical, applies to all modules)
DB host:     localhost on Hetzner; localhost on Windows dev
DB port:     5432
```

Local Windows dev fallback uses user `postgres` / password `postgres123` for
convenience. Production uses `nbne` user with password from `.env`
(`${DB_PASSWORD}`).

**Exceptions:**
- CRM uses Neon PostgreSQL (serverless, not local)
- Render uses PostgreSQL on nbne1 (`192.168.1.228`) or SQLite fallback
- Ledger local dev uses port 5433 to avoid conflicts

---

## Container and Compose Conventions

**Decided:** standardise on `-p <key>` so containers are self-describing.

```
docker compose -p <key> -f docker/docker-compose.yml up -d
```

This produces container names like `manufacture-backend-1`,
`deek-deek-api-1`, etc. Migrate existing modules during the next
maintenance window per module.

**Migration checklist per module:**
1. Stop existing containers: `docker compose down`
2. Update deploy script/workflow to include `-p <key>`
3. Start with new project name: `docker compose -p <key> up -d`
4. Verify container names: `docker ps --format '{{.Names}}'`
5. Update any `docker exec` commands in INFRASTRUCTURE.md

Until a module is migrated, its `INFRASTRUCTURE.md` must note the current
container naming scheme.

---

## Branch Convention

```
main                  Canonical branch on GitHub. Triggers auto-deploy.
master                Legacy local branch name on some clones.
```

**Rule:** all work must be pushed to `main`. If your local clone tracks
`master`, fix it: `git branch -m master main && git push -u origin main`
and update `git config init.defaultBranch main`.

**Exception — Ledger:** deploy script currently references `origin/master`.
Fix on next Ledger deploy.

This is a Pattern C trip-hazard — a fresh CC session that pushes to `master`
will silently fail to deploy.

---

## Networking — Cross-Module Coupling

Modules join Deek's compose network at runtime so they can reach the
brain's API endpoint. This is a deliberate runtime coupling.

**Decided:** rename the network from `deploy_default` to `deek_net`
post-rename for semantic clarity.

```
Network name (current):    deploy_default
Network name (target):     deek_net
```

The rename happens as part of the broader Deek rename (Phase 1 of §8).
Until then, `deploy_default` is what you type. After rename, update
every module's compose file to reference `deek_net`.

**Operational consequence:** if Deek's stack is not running, the module's
network reference fails and `docker compose up` errors. **Start the brain
first, then start modules.**

---

## Environment Variables — Cross-Module

These env vars must be identical across modules and the brain or
authentication breaks:

| Var | Purpose | Notes |
|---|---|---|
| `DEEK_API_KEY` | Bearer auth between modules and brain | Currently accepts `DEEK_API_KEY` as alias |
| `DEEK_API_KEY` | Same as above | Will become canonical post-rename |
| `DEEK_API_URL` | Brain API base URL | `http://deploy-deek-api-1:8765` from inside compose network |

**Rule during rename window:** code reads either `DEEK_API_KEY` or
`DEEK_API_KEY` (in that priority order), accepts whichever is set. Same
pattern for `*_API_URL`. New code writes `DEEK_*` only. After Phase 3 of the
rename (per discipline doc §8.4), `DEEK_*` fallbacks are removed.

---

## Marketplace Identifier Aliases

Amazon and module data refer to UK marketplace as `GB` in stored data.
Query code must translate via `MARKETPLACE_ALIASES` (defined in
`quartile_brief.py`). Passing `UK` to a raw orders query returns zero rows.

This is a known trap. Document it in any module that touches marketplace
identifiers.

---

## Deploy Mechanism

Per-module GitHub Actions workflow at `.github/workflows/deploy.yml`.
Triggers on push to `main`. Uses `appleboy/ssh-action`. Steps:

1. SSH to Hetzner with `HETZNER_SSH_KEY` secret
2. `cd /opt/nbne/<key>/docker/`
3. `git reset --hard origin/main`  — **destructive**
4. `docker compose -p <key> up -d --build`
5. `docker compose -p <key> exec backend python manage.py migrate --noinput`

**Critical:** step 3 is `git reset --hard`. Any uncommitted changes on the
server are destroyed. Never make hot-fixes directly on Hetzner — they will
be overwritten on next deploy. If you must hot-patch, immediately commit
the equivalent change to the repo and push it.

**Modules without CI/CD yet:** Render, CRM, Beacon, Ledger — deploy
manually per their `INFRASTRUCTURE.md`. Wire up GitHub Actions as each
module matures.

---

## Process Manager

Most modules run under Docker Compose. The exception is CRM, which uses
PM2 (`pm2 restart nbne-crm`).

For Docker Compose modules:

```
docker compose -p <key> restart <service>
docker compose -p <key> logs -f <service>
docker compose -p <key> exec <service> <command>
```

All commands run from the module's compose directory
(`/opt/nbne/<key>/docker/`) or with `-f`.

---

## Cron Jobs

**Decided:** migrate cron into per-module Django-Q2 schedules or dedicated
cron containers over time. Host-level crontab is hidden operational state
and too easy to lose.

**Migration path:**
- Modules already using Django-Q2 (Manufacture): move cron jobs into Q2
  scheduled tasks
- Modules using Celery Beat (Beacon): cron is already in-app
- Other modules: add a lightweight cron sidecar container to the compose
  stack, or use Django management commands triggered by compose `healthcheck`

**Until migrated:** document every host crontab entry in the relevant
module's `INFRASTRUCTURE.md`. A fresh CC session must be able to find
them without `crontab -l` on the server.

---

## Nginx and TLS

```
Site configs:    /etc/nginx/sites-enabled/
TLS certs:       /etc/ssl/cloudflare/      (Cloudflare origin certs)
```

Each module has one nginx site config that reverse-proxies to the backend
port.

**Decided:** version-control nginx configs. Each module should include its
nginx config in `docker/nginx/<key>.conf` within its own repo. The deploy
script syncs this to `/etc/nginx/sites-enabled/` on Hetzner.

**Modules already doing this:** Ledger (`docker/nginx/ledger.conf`),
Render (`docker/nginx/render.nbnesigns.co.uk.conf`).

**Modules to migrate:** Manufacture, Phloe, CRM, Deek — their nginx
configs currently live only on the server. Copy them into the repo on next
infrastructure pass.

---

## Email

All NBNE-internal transactional email goes through `smtplib` via IONOS SMTP.

`POSTMARK_SERVER_TOKEN` and `POSTMARK_SENDER` env vars are declared in
some compose files but **are not used anywhere** — dead config. Remove
on next pass per module.

Phloe tenant-facing email uses Resend API (primary) with IONOS SMTP as
fallback. This is separate from NBNE-internal email.

---

## What This File Does Not Cover

- Per-module domain vocabulary, primary users, UX principles
  -> see each module's `core.md`
- Per-module operational essentials (specific service names, log paths,
  module-specific gotchas)
  -> see each module's `INFRASTRUCTURE.md`
- The agent's procedure, cost discipline, delegation, write-back
  -> see `NBNE_PROTOCOL.md`
- The agent's scope and boundary rules
  -> see each repo's `CLAUDE.md`

---

## Resolved Decisions Log

Decisions made 16 April 2026 by Toby Fletcher:

- [x] SSH user — **keep `root`**. No deploy user migration.
- [x] Phloe path — **migrate to `D:\phloe`**. Both paths accepted until done.
- [x] Port allocation — **standardise on production reality** (8015/3015 for Manufacture, etc.)
- [x] Compose project naming — **standardise on `-p <key>`**. Migrate per module.
- [x] Cross-module network — **rename to `deek_net`** post-rename.
- [x] Host crontab — **migrate into per-module Django-Q2 / Celery / cron containers** over time.
- [x] Nginx configs — **version-control in each module's `docker/nginx/` directory**.

---

*End of document. Changes require a PR against nbne-policy and Pattern B
refinement before merge.*
