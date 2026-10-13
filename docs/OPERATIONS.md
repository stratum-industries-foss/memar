# MEMAR Operations Runbook

Day-2 operator reference: restart, backup, upgrade, migrations, secret rotation,
health checks. For initial setup see [INSTALL.md](../INSTALL.md); for env var
reference see [CONFIGURATION.md](CONFIGURATION.md).

All commands assume `docker-compose.yml` in the repo root and are run from
the repo root.

---

## Restart

**Config/code already on disk, no env changes** — just recycle the process:

```bash
docker compose restart memar
```

**You changed anything in `.env` (or exported new env vars)** — a plain
`restart` does NOT pick these up; env vars are only read at container
*start*, not by `restart`. Recreate the container instead:

```bash
docker compose down
docker compose up -d
```

Rule of thumb: `restart` for "something is stuck/misbehaving", `down && up -d`
for "I changed configuration."

---

## Backup

Two things need backing up — the SQLite database and the device config. They
are **not** in the same place.

### 1. Database (`memar_data` named volume)

`MEMAR_DB_PATH=/app/data/memar.db` inside the container, which lives on the
named volume `memar_data` (declared at the bottom of `docker-compose.yml`) —
this is Docker-managed storage, not a path on the host filesystem, so you
can't just `cp` it directly.

The container image doesn't ship the `sqlite3` CLI (`python:3.12-slim` base),
but Python's stdlib `sqlite3` module is available, so use that for a
consistent online backup, then copy the result out:

```bash
mkdir -p backups
docker compose exec memar rm -f /app/data/backup.db
docker compose exec memar python3 -c \
  "import sqlite3; sqlite3.connect('/app/data/memar.db').execute(\"VACUUM INTO '/app/data/backup.db'\")"
docker cp "$(docker compose ps -q memar)":/app/data/backup.db \
  "backups/memar-$(date +%Y%m%d-%H%M%S).db"
docker compose exec memar rm /app/data/backup.db
```

`VACUUM INTO` takes a live, consistent snapshot even while the app is
running — no need to stop the container first. The `rm -f` first is just
insurance in case a prior run left a stale `backup.db` behind (the command
errors if the target already exists).

For a full volume-level backup instead (covers the DB plus anything else
MEMAR writes to `/app/data`, e.g. admin credential files) — note this one is
**not** guaranteed point-in-time consistent if taken against a live
container (can catch a mid-write); stop the container first, or prefer
`VACUUM INTO` above for a live-safe snapshot:

```bash
docker run --rm -v memar_memar_data:/data -v "$PWD/backups":/backup \
  alpine tar czf /backup/memar-data-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
```

(Volume name is prefixed with the Compose project name — check the real name
with `docker volume ls | grep memar_data` if this doesn't match.)

### 2. Device config (`config/devices.example.yaml` or `config/devices.yaml`)

This is **not** in the database — it's a bind-mounted host directory
(`./config:/app/config` in `docker-compose.yml`), so it's already sitting on
the host at `config/` in the repo. Back it up like any other file:

```bash
cp config/devices.example.yaml backups/devices-$(date +%Y%m%d-%H%M%S).yaml
```

(If you set `MEMAR_CONFIG_PATH` to point somewhere else, back up that file
instead — check `docker-compose.yml`'s `MEMAR_CONFIG_PATH` env line or your
`.env` for the actual path in use.)

### Restore

Stop the container first — don't restore a DB file out from under a running
process holding open handles to it:

```bash
docker compose down

# Restore a VACUUM INTO snapshot (.db file):
docker run --rm -v memar_memar_data:/data -v "$PWD/backups":/backup \
  alpine cp /backup/memar-<timestamp>.db /data/memar.db

# ...or restore a full volume tarball instead:
docker run --rm -v memar_memar_data:/data -v "$PWD/backups":/backup \
  alpine sh -c "cd /data && tar xzf /backup/memar-data-<timestamp>.tar.gz"

cp backups/devices-<timestamp>.yaml config/devices.example.yaml
docker compose up -d
```

---

## Upgrade

This repo builds its own image from source (`build:` block in
`docker-compose.yml`) rather than pulling `ghcr.io/stratum-industries-foss/memar:latest`
by default — Compose only pulls the published tag if you don't have a local
build. Standard path is build-from-source:

```bash
git pull
docker compose build
docker compose up -d
```

If you're intentionally running the published image instead of building
locally, use `docker compose pull && docker compose up -d`.

**Before and after upgrading**, run the preflight validator to catch missing
or stale env vars — it checks what the app actually enforces (JWT secret in
prod, Stripe var coherence if billing is enabled, etc.), not a generic
checklist:

```bash
cd backend && ../.venv/bin/python scripts/preflight.py
# or, against a running container:
docker compose exec memar python3 backend/scripts/preflight.py
```

Take a database backup (above) before upgrading — schema changes are
additive-only and safe to run forward (see Migrations below), but there's no
built-in downgrade path if something goes wrong post-upgrade.

---

## Database Migrations

There is no Alembic (or any external migration tool) here. `backend/app/db.py`
uses a lightweight additive-column pattern:

- `init_db()` runs `Base.metadata.create_all` (creates any tables that don't
  exist yet) and then `_ensure_added_columns()`.
- `_ensure_added_columns()` walks a hardcoded map (`_ADDED_COLUMNS`) of
  `table → [(column, ddl), ...]` for columns that were added to
  *pre-existing* tables after the initial release (e.g. `webhooks.secret`,
  `users.must_change_password`), and issues `ALTER TABLE ... ADD COLUMN` for
  any that are missing. It's idempotent — checks `PRAGMA table_info` first,
  only adds what's not already there.

**In practice: migrations run automatically on every container start.**
There is no manual migration step, no `alembic upgrade head`, nothing to run
by hand. Just `docker compose up -d` (or `restart`) and `init_db()` handles
it.

The one thing to know: this is one-way. New columns get added; nothing gets
removed or renamed by this mechanism. If a future release ever needs a real
schema change (column removal/type change), it won't be handled by this
path — which is exactly why the backup step above matters before upgrading.

---

## Rotating Secrets

**`MEMAR_JWT_SECRET`** — signs all JWT access/refresh tokens. Rotating it
**logs out every active session** immediately (existing tokens fail
signature verification). Expected, not a bug — warn users first if this is a
live instance. After rotating, do the `down && up -d` restart (not a plain
`restart` — see above).

**Stripe keys** — if you rotate `MEMAR_STRIPE_SECRET_KEY`, no webhook impact.
But if you change the webhook *endpoint* (new public URL, new Cloudflare
Worker, etc.) or Stripe re-issues the signing secret for your existing
endpoint, you must also update `MEMAR_STRIPE_WEBHOOK_SECRET` to match — a
mismatched webhook secret fails signature verification on every incoming
Stripe event (checkout completions, renewals) silently until you check the
logs. Get the current signing secret from Stripe Dashboard → Developers →
Webhooks → your endpoint.

**License keys** (`MEMAR_LICENSE_PRIVATE_KEY`) — issuer-instance only, see
INSTALL.md. Rotating the keypair invalidates all previously-issued license
keys against the new public key; only do this if you're prepared to
re-issue.

---

## Health Check

```bash
curl -s http://localhost:8000/api/healthz | python3 -m json.tool
```

Returns app status plus operationally-useful context in one call — DB
connectivity, license state, and config load, not just a bare "ok":

```json
{
  "status": "ok",
  "version": "1.0.0",
  "build_id": "...",
  "db": "connected",
  "stripe_configured": false,
  "license_tier": "free",
  "license_active": true,
  "license_expires": null,
  "devices_licensed": 5,
  "adapters_configured": 2,
  "uptime_s": 1234
}
```

For a lighter check (used by the container's own `healthcheck:` in
`docker-compose.yml`), there's also `/api/readyz`, which just confirms the
device config loaded:

```bash
curl -s http://localhost:8000/api/readyz
# {"status": "ok", "printers": "2"}
```

Wire either into your uptime monitor; `/api/healthz` is more informative,
`/api/readyz` is cheaper (no DB round-trip on the printer count, and no
license/version lookups).
