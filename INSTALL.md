# MEMAR Installation Guide

## Requirements

- Docker, **or** a Linux host with systemd (or the `--no-service` mode for containers and WSL).
- For the Linux installer: Python 3.11 or newer (backend) and Node.js 20.19+ or 22.12+ (frontend build). `install.sh` fetches a standalone Python and the current Node LTS if yours is older or missing.

**Nothing has to be configured before first start.** MEMAR creates its own secrets, database and setup code.

### Staying current

Dependencies use minimum versions only, so a fresh install or upgrade gets the newest releases.
CI tests the newest releases on every supported Python and Node weekly, plus the minimum versions,
and Dependabot proposes updates for Python, npm, Rust, Docker base images and GitHub Actions.

- Docker: `docker compose pull && docker compose up -d`
- Linux installer: `git pull && bash install.sh`

---

## First start: the setup link

On first start MEMAR prints a one-time setup link to its log:

```
Open this link to finish setup: http://192.168.1.20:8000/setup?code=ABCD-EFGH
```

Open it, choose a username and password, and you are signed in. Clicking the link needs no typing.

- The link carries a one-time setup code. The first person to open it can claim the instance, so open it yourself promptly on a network you trust.
- Show the link again at any time: `docker exec memar memar setup-link` (Docker), or `sudo memar setup-link` (Linux service).
- Once set up, the command prints `MEMAR is already set up`. To reset the admin account, run `memar reset-admin`. It keeps devices and data.
- Setting `MEMAR_ADMIN_PASSWORD` in your environment creates the admin account at start instead. The setup link is then not used.

---

## Docker

### One command

```bash
# Prebuilt images are not published yet; build from this checkout:
docker build -t memar:local .
docker run -d --name memar --restart unless-stopped \
  -p 8000:8000 -v memar-data:/app/data \
  memar:local
docker logs memar
```

`docker logs memar` prints the setup link.

- Port: MEMAR listens on 8000 inside the container. Change the host port with `-p 8080:8000`.
- Data: everything (database, `devices.yaml`, logs, JWT secret, setup code) lives in the `memar-data` volume at `/app/data`.
- MEMAR runs as a non-root user (uid/gid 10001). On start, the container makes `/app/data` writable for that user, so a host folder works too: `-v ./memar-data:/app/data`. On a NAS, set `-e MEMAR_UID=… -e MEMAR_GID=…` to run as the folder's owner instead.
- Paid or air-gap licence: add `-e MEMAR_LICENSE_KEY=…`, or enter the key on the setup screen.

### With compose (recommended)

```bash
git clone https://github.com/stratum-industries-foss/memar && cd memar
docker compose up -d
docker logs memar
```

`docker-compose.yml` pulls the published image. No `.env` file is needed. To change a setting, copy `.env.example` to `.env` and uncomment only the lines you need. `MEMAR_HOST_PORT` sets the host port.

Compose needs v2.24 or newer.

To build the image from source instead of pulling it (for developers):

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

### Host networking (Linux, LAN discovery of printers)

```bash
docker compose -f docker-compose.yml -f docker-compose.host-network.yml up -d
```

MEMAR then shares the host network and listens on `MEMAR_PORT` (default 8000) directly on the host. Port mappings do not apply. Docker Desktop (macOS, Windows) does not expose the real LAN, so use this on Linux only.

### Upgrade and backup

```bash
docker compose pull && docker compose up -d       # upgrade; data stays in memar-data
docker run --rm -v memar-data:/data -v "$PWD":/backup alpine \
  tar -czf /backup/memar-data.tgz -C /data .      # backup
```

---

## Linux installer (systemd)

```bash
git clone https://github.com/stratum-industries-foss/memar && cd memar
bash install.sh                  # port 8000
bash install.sh --port 8080      # choose another port
```

Run it with `bash`, not `sh`. Run it as a normal user with sudo rights, or as root. Do not pipe it from `curl`: clone the repository first.

The installer:

- Installs system packages (Python, build tools, curl, rsync) with your distro's package manager.
- Builds the web UI (or uses the prebuilt one in the checkout).
- Stages a release under `/opt/memar/releases/<BUILD_ID>/`, owned by root and read-only to the service. The last three releases are kept.
- Writes `/etc/memar.env` (root only, 0600) with the port, paths and `MEMAR_ENV=production`. It contains no secrets. MEMAR creates the JWT secret on first start.
- Installs and starts `memar.service` under the `memar` user, with `ProtectSystem=strict`. Data lives in `/var/lib/memar` and the config in `/opt/memar/shared/config/devices.yaml`.
- Validates health (`/api/healthz`, `/api/readyz`, `/api/version`, `/`) and rolls back to the previous release on failure. On a first install that fails, the service is disabled and the installer prints the next step.
- Installs the `memar` command at `/usr/local/bin/memar`.
- Prints the setup link and the LAN address (`http://<ip>:<port>` and `http://<hostname>.local:<port>`).

Re-running the installer upgrades in place and keeps `/etc/memar.env`, the config and the data. It keeps the port already in use unless you pass `--port`.

The installer refuses to start when the port is held by another program, and names that program. Pick another port with `--port`.

### Commands

```bash
sudo memar setup-link            # show the setup link (or the sign-in URL once set up)
sudo memar status                # claimed or not, mode, URL
sudo memar reset-admin           # return to unclaimed; keeps devices and data
sudo systemctl restart memar     # restart
journalctl -u memar -f           # logs
```

### Settings

Edit `/etc/memar.env` (root). Only add what you need, for example Stripe or SMTP (see `.env.example` for the full list), then `sudo systemctl restart memar`.

### Uninstall

```bash
sudo bash scripts/uninstall.sh           # removes the service, releases and the memar command; keeps data and /etc/memar.env
sudo bash scripts/uninstall.sh --purge   # also removes /var/lib/memar, /etc/memar.env and the memar user
```

### Without systemd (containers, WSL)

```bash
bash install.sh --no-service --port 8123
```

This builds the environment and prints a foreground run command. The setup link is printed when MEMAR starts.

### Docker from the installer

```bash
bash install.sh --docker
```

Installs Docker and compose from your distro, then starts MEMAR with `docker compose`.

---

## Optional settings

All settings are optional. See `.env.example` for the full, commented list: Stripe, SMTP, alert webhooks, SSO, the messaging hub and tuning.

### License key (paid subscribers)

Free installs need no key. Paid and air-gap licences add a key. Give it in any of these ways:

| When | How |
|---|---|
| Docker, one command | `docker run -e MEMAR_LICENSE_KEY=... ...` (same flags as above) |
| Docker, compose | put `MEMAR_LICENSE_KEY=...` in `.env` next to `docker-compose.yml`, then `docker compose up -d` |
| Linux installer | `bash install.sh --license KEY`, or `bash install.sh --license-file PATH` (keeps the key out of your shell history) |
| After setup | paste it in the setup screen in the browser, or later under Settings → License |

The installer stores the key in `/etc/memar.env` (native, root only, 0600) or `.env` (Docker, 0600). It never prints the key. Re-running the installer with a new key replaces the old one.

**Air-gap licences make the setup code mandatory.** The first person to claim the instance must enter the code shown in the setup link (`memar setup-link`), even inside the first 10 minutes after start.

Other settings, for example Stripe or SMTP, go in the same place (see `.env.example`).

Two settings you may want early:

| Setting | Default | Purpose |
|---|---|---|
| `MEMAR_PUBLIC_URL` | LAN address | Base URL used in Stripe redirects and email links |
| `MEMAR_SETUP_MODE` | `auto` | First-account policy: `auto`, `open` (no code) or `code` (always a code) |

The license signing (private) key is for the issuer instance only. Customer and self-hosted installs never set it.

---

## Dev mode (local)

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000 --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev  # dev server at http://localhost:5173
```

The backend needs no environment variables for local development. The setup link is printed to the terminal.

---

## License key setup (issuer only)

Only the instance that receives Stripe webhooks and signs keys needs the private key. All instances need the public key for verification.

Generate an Ed25519 keypair:

```bash
python3 -c "
import nacl.signing, base64
sk = nacl.signing.SigningKey.generate()
print('Private:', base64.b64encode(bytes(sk)).decode())
print('Public: ', base64.b64encode(bytes(sk.verify_key)).decode())
"
```

On the issuer instance only, set `MEMAR_LICENSE_PRIVATE_KEY` to the private value. On all instances, set `MEMAR_LICENSE_PUBLIC_KEY` to the public value if you do not use the embedded key.

---

## Single sign-on (SAML 2.0)

Available on paid plans with the `sso` feature. Verified against a test identity provider in a real browser; check it against your own provider before you rely on it.

1. Sign in as an admin, open **Admin → SSO**, and fill in the SAML section:
   - **IdP entity ID** and **IdP sign-on URL** from your identity provider.
   - **IdP signing certificate (PEM)**: paste the public certificate. MEMAR pins it and does not fetch metadata at login.
   - **Service provider entity ID** (optional): leave blank to use `<your MEMAR address>/api/auth/saml/metadata`.
2. Give your identity provider the **assertion consumer URL** shown on the same screen (`<your MEMAR address>/api/auth/saml/acs`, HTTP-POST binding).
3. The **Sign in with SAML** button appears on the login page once the settings are saved and the plan is active.

Notes:
- A SAML user is created with the viewer role by default. Change it under **SSO default role**.
- A SAML name that matches an existing local account is refused, not signed in.
- If your identity provider rotates its signing key, paste the new certificate here. Until you do, MEMAR refuses logins, which is the intended behaviour.
- Set `MEMAR_PUBLIC_URL` to the address your browser uses (for example `https://memar.example.com`) so the assertion consumer URL is correct behind a proxy or port mapping.

## API tokens

A personal token lets a script or integration call the API as a user, without a password. Tokens are created by an admin.

```
POST /api/admin/api-tokens
{"name": "ci-read", "scope": "read", "expires_in_days": 90}
```

- The token (`mem_...`) is returned **once**. MEMAR stores only its hash; if you lose it, revoke it and create another.
- `scope: "read"` allows GET requests only. `scope: "full"` has the owner's role.
- `GET /api/admin/api-tokens` lists tokens without their values. `DELETE /api/admin/api-tokens/{id}` revokes one.
- A token stops working when it is revoked, when it expires, or when its owner is suspended.
- Use it as a bearer token: `Authorization: Bearer mem_...`.

## Audit log verification

Every audit entry is hash-chained to the one before it. `GET /api/admin/audit/verify` (admin, Pro and above) re-checks the chain and reports the first entry that was edited or removed. Entries written before the chain existed are reported as unchained, not as tampered.

The chain shows changes made after the fact. It does not stop someone with database access from rewriting the whole chain, so compare the reported chain head with a copy kept elsewhere if you need that guarantee. The compliance export (`GET /api/admin/audit/export`, CSV or JSON) includes the chain head.

## Stripe webhook (production)

1. Create products and prices in the Stripe Dashboard. Copy the Price IDs into `MEMAR_STRIPE_PRICE_*`.
2. Expose your instance publicly (Cloudflare Tunnel recommended):
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. In the Stripe Dashboard, add a webhook endpoint at `https://<your-host>/stripe/webhook`.
4. Subscribe to the events MEMAR handles: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `invoice.payment_action_required`, `customer.subscription.updated`, `customer.subscription.paused`, `customer.subscription.deleted`.
5. Copy the webhook signing secret into `MEMAR_STRIPE_WEBHOOK_SECRET`.
6. Set `MEMAR_PUBLIC_URL` to your public address.

Do not set `MEMAR_STRIPE_WEBHOOK_SECRET` if you use the Cloudflare Worker for key issuance. Both would send duplicate license emails.

---

## Support

**Bug reports (OSS):** [GitHub Issues](https://github.com/stratum-industries-foss/memar/issues). Include the output of:

```bash
curl -s http://localhost:8000/api/support-info | python3 -m json.tool
```

**Paid tier support:** email support@stratum.industries
