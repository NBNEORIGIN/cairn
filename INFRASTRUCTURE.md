# INFRASTRUCTURE.md
# Deek (formerly Deek, formerly Claw) — Operational Essentials
# Force-loaded by every Deek CC session via CLAUDE.md.
# Last updated: 16 April 2026

---

## Purpose

Every operational fact you need to work on Deek without having to ask.
SSH targets, deploy commands, env vars, container names, Ollama model
setup, API server start commands, MCP server start commands, log paths,
gotchas. If you can't proceed because you don't know an operational
detail — first check this file. If it's not here and it should be, add it
after completing the task that needed it.

---

## Naming Reality vs. Target

This is the Deek repo. Operationally, almost everything is still named
`cairn` or `deek`. The rename is in progress per the discipline doc §8.
The table below shows current reality vs. target post-rename.

| What | Current | Post-rename |
|---|---|---|
| Local repo path | `D:\deek\` | `D:\deek\` |
| Hetzner repo path | `/opt/nbne/deek/` | `/opt/nbne/deek/` |
| Hetzner compose dir | `/opt/nbne/deek/docker/` | `/opt/nbne/deek/docker/` |
| Public URL | `https://deek.nbnesigns.co.uk` | `https://deek.nbnesigns.co.uk` (cairn alias retained during migration) |
| API container | `deploy-deek-api-1` | `deploy-deek-api-1` (cairn alias retained) |
| Cross-module network | `deploy_default` | `deek_net` (proposed, see LOCAL_CONVENTIONS.md OPEN) |
| API env var (auth) | `DEEK_API_KEY` (also `DEEK_API_KEY`) | `DEEK_API_KEY` (legacy aliases accepted during migration) |
| API env var (URL) | `DEEK_API_URL` | `DEEK_API_URL` |
| Hardware profile env | `DEEK_HARDWARE_PROFILE` | `DEEK_HARDWARE_PROFILE` |
| Force-API mode env | `DEEK_FORCE_API` | `DEEK_FORCE_API` |
| Database name | `cairn_db` | `deek_db` (deferred to Phase 5 — internal, low-value to rename) |
| API path prefix | `/api/cairn/` | `/api/deek/` (cairn alias retained) |

The rest of this file uses **current operational names** (cairn, deek)
because that's what you type today. Where commands change after rename,
that's noted inline.

---

## Hetzner Production

| Item | Value |
|---|---|
| IP | `178.104.1.152` |
| SSH | `ssh root@178.104.1.152 -i ~/.ssh/id_ed25519` |
| Port | 22 |
| User | `root` (see `LOCAL_CONVENTIONS.md` OPEN) |
| Repo path | `/opt/nbne/deek/` |
| Compose dir | `/opt/nbne/deek/docker/` |
| Public URL | `https://deek.nbnesigns.co.uk` |
| API port | `127.0.0.1:8765` (nginx reverse-proxies) |
| DB name | `cairn_db` |
| DB user | `nbne` |
| DB password | `${DB_PASSWORD}` from `/opt/nbne/deek/.env` |

---

## Container Names (Compose)

The compose project name on Hetzner is `deploy` (derived from a parent
directory or set explicitly), so containers are named with the
`deploy-` prefix:

```
deploy-deek-api-1     ← the FastAPI server
deploy-deek-db-1      ← Postgres + pgvector
deploy-cairn-ollama-1  ← Ollama for local models (if containerised)
```

This is why consumer modules join the network `deploy_default` to reach
`deploy-deek-api-1:8765`.

**OPEN per LOCAL_CONVENTIONS.md:** the `deploy-` prefix is opaque and
should probably become `deek-` post-rename. Coordinated as part of the
broader compose-project-name standardisation.

---

## Local Windows Dev

| Item | Value |
|---|---|
| Repo path | `D:\deek\` |
| Python venv | `D:\deek\.venv\` |
| API server | See "Starting the API" below |
| MCP server | `D:\deek\mcp\deek_mcp_server.py` |
| Local DB | Postgres on `localhost:5432`, db `cairn_db`, user `postgres`, password `postgres123` |
| Ollama models dir | `D:\ollama-models\` (redirected from C: to free space) |

---

## Starting the API (Local)

```powershell
cd D:\deek
.\.venv\Scripts\python -m uvicorn api.main:app --host 0.0.0.0 --port 8765
```

Verify it's running:
```
GET http://localhost:8765/health
```

Expected response:
```json
{
  "status": "ok",
  "projects_loaded": [...],
  "model_tier_active": "...",
  "memory_entries_total": ...
}
```

If port 8765 is already in use:
- Use Task Manager to kill the process (PowerShell `Stop-Process` returns
  access denied)
- Then restart per the command above

---

## Starting the API (Hetzner)

Normally managed by Docker Compose:

```
ssh root@178.104.1.152 -i ~/.ssh/id_ed25519
cd /opt/nbne/deek/docker/
docker compose up -d
```

Verify:
```
curl http://localhost:8765/health
```

Or from a consumer module's container:
```
docker compose exec backend curl http://deploy-deek-api-1:8765/health
```

---

## MCP Server

The MCP server is a thin wrapper over the FastAPI that exposes Deek's
tools to MCP-compatible clients (Claude Code, Codex, etc.).

Path: `D:\deek\mcp\deek_mcp_server.py` (becomes `deek_mcp_server.py`
post-rename).

Install MCP SDK if needed:
```
pip install mcp --break-system-packages
```

Register in Claude Code's MCP config (per CC's documentation — the
configuration file location depends on your CC install). The server
exposes:

- `retrieve_codebase_context`
- `retrieve_chat_history`
- `update_memory`
- `list_projects`
- `get_project_status`
- `deek_delegate` (becomes `deek_delegate` post-rename)

Full tool specifications: `core.md` and the MCP spec doc.

---

## Ollama and Local Models

### Models directory
```
D:\ollama-models\
```

### Currently installed (dev_desktop profile, RTX 3050 8GB)

| Model | Tag | Purpose | VRAM behaviour |
|---|---|---|---|
| Qwen 2.5 Coder 7B | `qwen2.5-coder:7b` | Code generation | Fits fully in VRAM |
| Gemma 4 (E4B) | `gemma4:e4b` | General reasoning, conversational, PA | Spills ~68% to CPU/RAM |
| DeepSeek Coder V2 16B | `deepseek-coder-v2:16b` | Hard code reasoning | Heavy CPU spill |
| nomic-embed-text | `nomic-embed-text` | Embeddings for pgvector | Tiny, always resident |

### To pull on dual_3090 arrival (planned)
```
ollama pull qwen2.5-coder:32b
ollama pull deepseek-coder-v2:16b
ollama pull mxbai-embed-large
```

Then update env: `DEEK_HARDWARE_PROFILE=dual_3090` (becomes
`DEEK_HARDWARE_PROFILE=dual_3090` post-rename).

Routing matrix per profile lives in `core.md`.

### Constraint
On `dev_desktop`, models cannot all be loaded simultaneously at full
performance — Ollama swaps them. If VRAM pressure becomes acute,
dedicate the card to one model and route remaining work to API.

---

## Environment Variables

### Required for API operation

| Var | Purpose | Notes |
|---|---|---|
| `DB_PASSWORD` | Postgres password | Must match db init |
| `DEEK_API_KEY` (or `DEEK_API_KEY`) | Bearer token consumers use | Must match every module's env |
| `DEEK_HARDWARE_PROFILE` | `dev_desktop` or `dual_3090` | Determines model routing |
| `DEEK_FORCE_API` | `true`/`false` | When `true`, bypass local models |
| `OPENROUTER_API_KEY` | For `deek_delegate` calls to Grok/Haiku | Required for cost discipline routing |
| `ANTHROPIC_API_KEY` | For Claude API escalation | Optional — only if API tier used |

### Cost log destinations

Cost data is written to two places:
1. Deek (Deek) PostgreSQL `cost_log` table (queryable, feeds business brain)
2. `data/cost_log.csv` (human-readable, survives DB failures)

---

## Common Operations

### Restart the API after a code change
```powershell
# Local: kill the uvicorn process (Task Manager) and restart per "Starting the API"
```

```bash
# Hetzner:
cd /opt/nbne/deek/docker/
docker compose restart deek-api
```

### Reindex a project after files changed
```
POST http://localhost:8765/index?project=<project>
```

### Compile / re-embed wiki articles
```
POST http://localhost:8765/api/wiki/compile?scope=modules
POST http://localhost:8765/api/wiki/compile?scope=patterns
POST http://localhost:8765/api/wiki/compile?scope=decisions
```

### Check loaded projects
```
GET http://localhost:8765/projects
```

### Run contract evals on Deek itself
```
cd D:\deek
.\.venv\Scripts\python -m pytest evals/
```

(Hetzner equivalent uses `docker compose exec`.)

---

## Networking

### The shared compose network
```
deploy_default  ← current actual name
deek_net        ← proposed post-rename per LOCAL_CONVENTIONS.md
```

Modules join this network to reach `deploy-deek-api-1:8765`. Deek's
compose stack is the network's owner. **Start Deek before starting any
module** — module compose stacks fail if the network doesn't exist.

### Nginx
| Item | Value |
|---|---|
| Site config | `/etc/nginx/sites-enabled/cairn` (becomes `deek` post-rename) |
| TLS certs | `/etc/ssl/cloudflare/` |
| Reverse-proxy target | `127.0.0.1:8765` |

---

## Splash Screen / Shell Frontend (Planned)

Per `core.md` (Shell Frontend section), a PowerShell / CMD frontend will
be built that displays on session start. Not yet implemented. When built:

- Calls `GET /health` on startup
- Renders ASCII art splash + project status + active model tier
- Provides a `> What are we building today?` prompt
- Falls back gracefully if Unicode block characters unsupported

---

## Deploy Mechanism

### CI/CD

| Item | Value |
|---|---|
| Workflow file | `.github/workflows/deploy.yml` |
| Trigger | Push to `main` |
| Mechanism | `appleboy/ssh-action` |
| Required GitHub secret | `HETZNER_SSH_KEY` |

The deploy workflow does the standard:
1. SSH to Hetzner
2. `cd /opt/nbne/deek/docker/`
3. `git reset --hard origin/main` ← **destructive**
4. `docker compose up -d --build`
5. `docker compose exec deek-api python manage.py migrate --noinput`
   (or equivalent for FastAPI's migration approach — see project README)

**Critical for Deek specifically:** Deek's deploy can break every
consumer module because they depend on Deek's network and API. Before
deploying Deek:

- Verify no consumer modules are mid-deploy (race condition)
- Verify nothing about the network name, container name, or port has
  changed (those are spanning briefs)
- Run contract evals locally before pushing

---

## Module Polling Schedule

Deek's scheduled polling jobs (run by APScheduler or Django-Q2 — see
`core.md`):

| Module | Endpoint | Cadence |
|---|---|---|
| Manufacture | `/api/cairn/context` | Every 30 min during working hours |
| Ledger | `/api/cairn/context` | Every 60 min |
| Marketing (CRM + Phloe ads) | `/api/cairn/context` | Every 4 hours |
| AMI scheduler | (multiple endpoints) | Per AMI module config |

Each polled response is cached for the poll interval and indexed into
memory. Cached responses age out and are flagged stale to the brain.

The AMI scheduler has been flagged as a fragile single point of failure —
decoupling to Windows Scheduled Task is on the backlog (per user
memory). Address before relying on AMI in production.

---

## Module-Specific Gotchas

### 1. The git_commit tool used to map to git_add
Historical bug — confirm in current code whether
`core/tools/git_tools.py` and `core/tools/registry.py` map tools
correctly. Run a test commit from inside the agent loop after any change
to the registry.

### 2. The MCP server may need a manual restart after registry changes
If you add or rename a tool in the registry, the MCP server's tool list
is cached at startup. Restart the MCP server to refresh.

### 3. DEEK_FORCE_API=true is a hard escape hatch
Bypasses all local model routing and sends everything to API. Useful for
debugging when local models are misbehaving. **Has cost implications** —
do not leave on in production.

### 4. The wiki compile is not automatic on file changes
Wiki articles in `wiki/modules/`, `wiki/patterns/`, `wiki/decisions/`
must be explicitly compiled and embedded after editing. Either:
- Manual: `POST /api/wiki/compile?scope=modules` after editing
- Or include the compile call in any task that touches wiki

Step 4 of the protocol covers this for module wiki articles. Apply the
same to Deek's own wiki.

### 5. Web UI vs API
`build-deek.bat` + `npm start` builds and serves the web UI at
`localhost:3000`. The API on port 8765 is the system; the web UI is
optional. Do not start the web UI unless asked. Use `npm start`, not
`npm run dev`.

### 6. Port 8765 must not move
Every consumer module hardcodes this port. Changing it is a spanning
brief affecting every module's configuration.

### 7. The Project Registry needs to be kept current
Adding a module to NBNE means adding it to Deek's project registry
(currently in config files; eventually queried via `list_projects`).
Stale registry → stale routing → silent failures.

### 8. Logs path may not exist on first run
`logs/` should be in `.gitignore` (per existing CLAUDE.md). If logs
reappear in `git status`, run `git rm -r --cached logs/` and verify
`.gitignore` covers them.

---

## What's Not Here

- The breadth classifier matrix (in `core.md`)
- The WIGGUM loop contract (in `core.md`)
- The MCP tool specifications (in `core.md`)
- The memory architecture (in `core.md`)
- The cost tracking module schema (in `core.md`)
- Module API contract schemas (in `DEEK_MODULES.md`)
- Backup and restore procedures for the Deek DB (TODO — Deek's memory is
  arguably the most valuable single piece of data NBNE has)
- Disaster recovery runbook (TODO — depends on backup)

---

*End of document. Updates require a date in the header.*
