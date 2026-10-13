# MEMAR Installation Guide

## Requirements

- Python 3.9+ (backend)
- Node.js 18+ (frontend build)
- Linux host (systemd) or Docker

---

## Docker (recommended)

### 1. Generate a JWT secret

```bash
openssl rand -hex 32
```

### 2. Create a .env file

```bash
cp .env.example .env  # or create from scratch
```

Minimum required variables:

```
MEMAR_JWT_SECRET=<output of openssl rand -hex 32>
```

Optional (enables billing):

```
MEMAR_STRIPE_SECRET_KEY=sk_live_...
MEMAR_STRIPE_PRICE_MAKER=price_...
MEMAR_STRIPE_PRICE_PRO=price_...
MEMAR_STRIPE_PRICE_FARM=price_...
MEMAR_STRIPE_PRICE_SCALE=price_...
MEMAR_PUBLIC_URL=https://memar.yourdomain.com
```

**Self-hosted webhook mode** (if you are NOT using the Cloudflare Worker):
```
MEMAR_STRIPE_WEBHOOK_SECRET=whsec_...
MEMAR_LICENSE_PRIVATE_KEY=<base64 ed25519 private key>
MEMAR_SMTP_HOST=smtp.gmail.com
MEMAR_SMTP_PORT=587
MEMAR_SMTP_USER=you@gmail.com
MEMAR_SMTP_PASSWORD=<gmail app password>
MEMAR_SMTP_FROM=you@gmail.com
```

⚠️ **Do not set `MEMAR_STRIPE_WEBHOOK_SECRET` if you are using the Cloudflare Worker for key issuance.** If both the backend and the Worker have this secret configured against the same Stripe webhook endpoint, you will get double key emails on every purchase.

### 3. Start

```bash
docker compose up -d
```

MEMAR listens on port 8000 (mapped from internal 9000).

### 4. First login

Default admin user: `admin`, with the password you set in `MEMAR_ADMIN_PASSWORD`. `docker compose` will not start until both `MEMAR_JWT_SECRET` and `MEMAR_ADMIN_PASSWORD` are set.

---

## Bare-metal / systemd (Debian, Armbian, or other Linux)

Use the provided install script for a full blue/green deployment with automatic rollback:

```bash
cd memar
./scripts/install_systemd_service.sh
```

This will:
- Create a `memar` system user
- Stage the release under `/opt/memar/releases/<BUILD_ID>/`
- Build the frontend and embed it into the backend static path
- Write `/etc/memar.env` (generates MEMAR_JWT_SECRET if not set — save the output)
- Install and start `memar.service` via systemd
- Validate health (`/api/healthz`, `/api/version`, `/`) and roll back on failure

After install, edit `/etc/memar.env` to add Stripe and SMTP credentials, then:

```bash
sudo systemctl restart memar
```

---

## Dev mode (local)

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
MEMAR_JWT_SECRET=$(openssl rand -hex 32) uvicorn app.main:app --port 9000 --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev  # dev server at http://localhost:5173
```

---

## License key setup (license issuer only — the instance that receives Stripe webhooks)

Generate an Ed25519 keypair:

```bash
python3 -c "
import nacl.signing, base64
sk = nacl.signing.SigningKey.generate()
print('Private:', base64.b64encode(bytes(sk)).decode())
print('Public: ', base64.b64encode(bytes(sk.verify_key)).decode())
"
```

Set `MEMAR_LICENSE_PRIVATE_KEY` to the private key value and `MEMAR_LICENSE_PUBLIC_KEY` to the public key value in your env file. Only the webhook-receiving instance needs the private key — all instances need the public key for verification.

---

## Stripe webhook (production)

1. Create products and prices in Stripe Dashboard, copy Price IDs into `MEMAR_STRIPE_PRICE_*` env vars.
2. Expose your instance publicly (Cloudflare Tunnel recommended):
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. In Stripe Dashboard, add a webhook endpoint pointing at `https://<your-host>/stripe/webhook`.
4. Subscribe to the events MEMAR handles: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `invoice.payment_action_required`, `customer.subscription.updated`, `customer.subscription.paused`, `customer.subscription.deleted`.
5. Copy the webhook signing secret into `MEMAR_STRIPE_WEBHOOK_SECRET`.

---

## Support

**Bug reports (OSS):** [GitHub Issues](https://github.com/stratum-industries-foss/memar/issues) — include your `/api/support-info` output:

```bash
curl -s http://localhost:8000/api/support-info | python3 -m json.tool
```

**Paid tier support:** email support@stratum.industries
