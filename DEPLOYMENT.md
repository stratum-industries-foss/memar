# MEMAR Deployment Guide

## Quick Start (5 minutes)

### Prerequisites
- Python 3.12+, SQLite, Git
- For dev: `nix-shell` (optional; installs all deps)
- For production: Docker & Docker Compose

### Ports

- **Docker:** the app listens on 9000 inside the container; `docker-compose.yml` maps it to **http://localhost:8000**.
- **Bare metal / systemd:** the app listens on **9000** (`deploy/systemd/memar.service`, `scripts/install_systemd_service.sh`).
- **Local development:** run the backend on **8000**, which is where the Vite dev server proxies `/api` and `/ws` (`frontend/vite.config.ts`).

### Development Server

```bash
# Clone and enter the repo
git clone https://github.com/stratum-industries-foss/memar.git && cd memar

# Option A: Using nix-shell (recommended)
nix-shell
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# Option B: Manual venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev  # Runs on :5173

# Visit: http://localhost:5173
# First login: admin / admin (dev only; you must change it on first login).
# Set MEMAR_ADMIN_PASSWORD to skip the default. Production requires it.
```

---

## Architecture Overview

### Layer Stack

| Layer | Responsibility | Key Files |
|-------|---|---|
| **Auth** | JWT tokens, refresh tokens, user CRUD | `backend/app/auth.py` |
| **License** | Feature gating, Ed25519 verification | `backend/app/license.py` |
| **OEE** | Overall Equipment Effectiveness analytics | `backend/app/oee.py` |
| **Fleet** | Printer discovery, control, webhooks | `backend/app/fleet.py` |
| **FloorPlan** | Device location visualization | `backend/app/floorplan.py` |
| **Config** | YAML device definition, hot-reload | `backend/app/config.py` |
| **Database** | SQLite (async), schema at startup | `backend/app/db.py`, `models_db.py` |

### Database Schema

```
User (id, username, password_hash, role, team_id, is_active, created_at)
├─ RefreshToken (token_hash, expires_at, revoked)
├─ Webhook (url, events[], active)
└─ AuditLog (action, resource, detail, ip_address)

Team (id, name, description) ─── 1:N ─── User
FloorPlanLayout (device_id, x, y, rotation)
```

### Feature Gating (Tiers)

The free tier allows 5 devices with core monitoring. Every paid tier unlocks the same feature set (audit logs, compliance export, custom branding, email alerts, SSO, OEE, floor plan, and the rest); tiers differ only in device limit. The compliance export (`GET /api/admin/audit/export`) writes the real audit rows with their hash-chain fields and the chain head, so an auditor can check them; it does not generate summaries. See https://stratum.industries/memar for current limits and prices. Support response times are not part of the software license.

---

## Configuration

### Environment Variables

```bash
# Required (production)
MEMAR_JWT_SECRET=<64-char random string>        # e.g., openssl rand -hex 32
MEMAR_ADMIN_USER=admin
MEMAR_ADMIN_PASSWORD=<secure password>          # Required in production; dev default is admin/admin (forced change)
MEMAR_LICENSE_KEY=<base64-encoded key>          # For paid tiers (see License Generation)

# Optional (dev defaults shown)
MEMAR_CONFIG_PATH=./config/devices.example.yaml # Device list (YAML)
MEMAR_DB_PATH=./data/memar.db                   # SQLite database location
MEMAR_DATA_DIR=./data                           # Persistent data volume
```

### Device Configuration (YAML)

File: `config/devices.example.yaml`

```yaml
farm_name: "My Shop Floor"
printers:
  - id: printer_001
    name: "Prusa i3 MK4"
    protocol: moonraker
    base_url: "http://192.168.1.100:7125"  # Moonraker API
    enabled: true
  - id: printer_002
    name: "Bambu X1C"
    protocol: bambu
    base_url: "http://192.168.1.101:8800"
    enabled: false  # Hidden from UI
```

Hot-reload: Change the config file; backend auto-reloads on next request.

### CORS Configuration

Controlled via the `MEMAR_CORS_ORIGINS` environment variable (default: `http://localhost:5173,http://localhost:8080,http://localhost:3000`):

```python
# backend/app/main.py
_cors_origins_raw = os.getenv("MEMAR_CORS_ORIGINS", "http://localhost:5173,http://localhost:8080,http://localhost:3000")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)
```

For production, set `MEMAR_CORS_ORIGINS=https://yourdomain.com`.

---

## Running the Server

### Nix-Shell (Recommended)

```bash
nix-shell  # Enters shell with all deps
uvicorn backend.app.main:app --host 0.0.0.0 --port 9000
```

### Docker Compose (Quickest)

```bash
docker-compose up -d
# Logs: docker compose logs -f
# Stop: docker compose down
```

**Note:** Uses `python:3.12-slim` image; named volume `memar_data` persists the DB.

### Manually (venv)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 9000
```

### Frontend (Development)

```bash
cd frontend
npm install
npm run dev  # Vite dev server on :5173, proxies API to :8000
```

For production, build and serve:

```bash
npm run build        # Outputs to ../frontend_dist/
npm run preview      # Test the build locally
```

Backend serves the SPA from `frontend_dist/` as a fallback.

### Health Checks

```bash
curl http://localhost:9000/api/healthz    # { "status": "ok", "uptime_s": 123 }
curl http://localhost:9000/api/readyz     # { "status": "ok", "printers": "2" }
curl http://localhost:9000/api/version    # { "version": "1.0.0", "build_id": "..." }
```

---

## Testing

### Auth Flow Test

```bash
# Run the smoke test
bash scripts/verify_fixes.sh

# Output shows:
# ✓ Health check
# ✓ POST /api/auth/login succeeds
# ✓ Protected endpoint without token → 403
# ✓ Protected endpoint with token → 200
```

### Manual Endpoint Tests

```bash
# Login
curl -X POST http://localhost:9000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "test"}' | jq .

# Get printers (requires token from login)
TOKEN="<access_token from login>"
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:9000/api/printers | jq .

# OEE analytics (paid tiers)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:9000/api/oee | jq .
```

---

## Deployment to Docker

### Basic Docker Compose (Included)

```bash
docker-compose up -d
```

Set environment variables in `.env` or inline:

```bash
MEMAR_JWT_SECRET=your-secret \
MEMAR_ADMIN_PASSWORD=your-password \
MEMAR_LICENSE_KEY=your-license-key \
docker-compose up -d
```

### Production Hardening

1. **Restrict CORS origins:**
   - Set `MEMAR_CORS_ORIGINS=https://yourdomain.com`

2. **Enable HTTPS:**
   - Use a reverse proxy (nginx, Caddy, HAProxy)
   - Terminate TLS at the edge, forward to the app port (9000 bare metal, 8000 Docker)

3. **Secrets management:**
   - Use Docker secrets or `.env` files (not in git)
   - Rotate MEMAR_JWT_SECRET periodically (invalidates all tokens)

4. **Database backup:**
   - Mount `memar_data` to a volume with snapshots enabled
   - Scheduled `sqlite3 /app/data/memar.db ".backup /backups/memar-$(date +%Y%m%d-%H%M%S).db"`

5. **Monitor logs:**
   - `docker compose logs -f memar` or systemd journal

---

## Auto-Detection Setup (Optional)

MEMAR can automatically scan your local network for connected printers and devices. By default, the `docker-compose.yml` deployment isolates the MEMAR container from your LAN (bridge networking). To enable auto-detection, you have two options:

### Option A: Linux Docker (Recommended)

On a Linux Docker host, layer on an additional compose file to give MEMAR direct network access:

```bash
docker compose -f docker-compose.yml -f docker-compose.host-network.yml up -d
```

This uses `network_mode: host`, which grants the container the same LAN visibility MEMAR already needs to reach your Moonraker, OctoPrint, and other controllers directly. This is **not** a new trust boundary — it's the same LAN access the app requires for normal operation.

### Option B: Bare-Metal / Systemd

If you installed MEMAR via the systemd service (`deploy/systemd/memar.service`), auto-detection is already available with no changes needed. The systemd process runs with full host networking by default.

### Limitations

- **Docker Desktop (Mac/Windows)**: Even with `network_mode: host`, Docker Desktop's VM-backed networking cannot reach the real LAN. Auto-detection will find 0 devices, which is expected. Add printers manually via the "Add manually" option in the wizard instead.
- **Multi-subnet / VLAN deployments**: The auto-detect scan probes only the local `/24` subnet where the MEMAR server is connected. If your printers are on a different subnet, you will need to add them manually or configure additional network routes.

### Troubleshooting

If you enabled host mode but the scan still returns 0 devices:
1. Verify at least one printer is powered on and connected to your network
2. Check that your printer is running on port 7125 (Moonraker) or 80/5000 (OctoPrint) — if it's on a different port or protocol, add it manually via the "Add manually" option
3. If behind a firewall, ensure MEMAR can reach the printer's port (typically only TCP outbound is needed for the scan to work)

---

## License Generation

Use the bundled key tool (run from the repo root, with backend dependencies installed).

### Generate a signing keypair (once)

```bash
python -m tools.keygen.keygen --generate-keypair --privkey ./memar_private.key --pubkey ./memar_public.key
```

Both files are base64. Keep the private key offline and out of git. Give every MEMAR instance the public key via `MEMAR_LICENSE_PUBLIC_KEY`.

### Generate a license

```bash
python -m tools.keygen.keygen --customer-id CUST_12345 --tier farm --device-limit 150 --days 365 --privkey ./memar_private.key
```

The tool prints the license as a base64 string (`--days 0` means no expiry).

### Activate

```bash
export MEMAR_LICENSE_KEY="<base64 license from the previous step>"
export MEMAR_LICENSE_PUBLIC_KEY="$(cat memar_public.key)"
# Restart the server; the license is verified at startup
```

Check license status:

```bash
curl http://localhost:9000/api/license/status | jq .
```

---

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| **FastAPI not found** | Running outside nix-shell / venv | `nix-shell` or `source .venv/bin/activate` |
| **Port in use** | Another process owns it | `lsof -i :9000` (or `:8000`), or start uvicorn with a different `--port` |
| **Admin password not set** | `MEMAR_ADMIN_PASSWORD` missing | Required in production. In dev the default is admin/admin with a forced change |
| **License invalid** | Wrong public key or expired | Set `MEMAR_LICENSE_PUBLIC_KEY` to the public half of the keypair that signed the license |
| **Database locked** | Multiple writers (SQLite limit) | Ensure only one uvicorn process; SQLite → PostgreSQL for scale |
| **Config not loading** | YAML syntax error | Validate with `python -c "import yaml,sys; yaml.safe_load(open('config/devices.yaml'))"` |
| **WebSocket timeout** | Firewall blocks ws:// upgrade | Check reverse proxy (nginx) allows WebSocket upgrades |

---

## Next Steps

- **Configure devices:** Copy `config/devices.example.yaml` to `config/devices.yaml` and edit it
- **Add users:** Sign in as admin and create users in the admin panel
- **Enable webhooks:** Create endpoints in fleet settings to publish state changes
- **Set up floor plan:** Upload a shop floor image, drag devices onto it (paid tiers)
- **Monitor OEE:** Track Availability, Performance, Quality per printer (paid tiers)

---

**Version:** 1.0.0  
**License:** AGPL-3.0
