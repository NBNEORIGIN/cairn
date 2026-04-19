# Postgres migrations

Numbered idempotent SQL files applied at API startup, in lexicographic
order. A small bootstrapper (`core/memory/migrations.py`) records which
files have been applied in a `schema_migrations` table and skips them
on subsequent boots.

## Conventions

- Filenames: `NNNN_snake_case_description.sql`, zero-padded (`0001_…`,
  `0002_…`). Lexicographic order is the apply order.
- Every statement must be idempotent — use `CREATE TABLE IF NOT EXISTS`,
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT
  EXISTS`, etc. If a migration runs twice, nothing should break.
- One logical change per file. Don't retro-edit an already-applied
  migration — write a new one.
- Comment at the top of each file links the commit or brief that
  motivated it.
- Do not use transactions — individual statements are atomic; wrapping
  in `BEGIN/COMMIT` defeats partial recovery if one statement fails.

## Why no Alembic / Django migrations

Deek's API doesn't use an ORM. The SQLite side already uses defensive
`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN` at startup
(see `core/memory/store.py::_ensure_schema`). This mirrors that pattern
for Postgres. Keep it simple; no migration framework to maintain.

## Running manually

```bash
# Inside the api container:
docker exec -e PYTHONPATH=/app deploy-deek-api-1 \
  python -m core.memory.migrations

# Locally:
python -m core.memory.migrations
```

## Rollback

There is no automatic rollback. If a migration breaks production,
write a new migration that reverts it — don't delete the broken one
from the apply history.
