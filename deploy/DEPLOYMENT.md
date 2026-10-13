# MEMAR Deployment Guide

Production deployment for MEMAR on a Linux host (systemd + Docker or bare-metal uvicorn).

---

## Prerequisites

- Python 3.9+ with venv or Docker + docker-compose
- Outbound SMTP access (Gmail app password recommended)
- Stripe account (for billing features)
- Cloudflare tunnel or reverse proxy for public URL

---

## 1. Environment Variables

Copy and fill in `backend/.env`:

```bash
cp backend/.env.example backend/.env   # or create from the template below
```

Required before first run:

```bash
# Security — generate with: openssl rand -hex 32
MEMAR_JWT_SECRET=<64-char hex>

# Data directory (default: ./data)
MEMAR_DATA_DIR=/var/lib/memar

# Public URL (used in email links, Stripe webhooks)
MEMAR_PUBLIC_URL=https://memar.yourdomain.com

# SMTP (Gmail: use an App Password, not your account password)
MEMAR_SMTP_HOST=smtp.gmail.com
MEMAR_SMTP_PORT=587
MEMAR_SMTP_USER=you@gmail.com
MEMAR_SMTP_PASSWORD=<app-password>
MEMAR_SMTP_FROM=MEMAR <you@gmail.com>

# Stripe (leave empty to disable billing)
MEMAR_STRIPE_SECRET_KEY=sk_live_...
MEMAR_STRIPE_WEBHOOK_SECRET=whsec_...
MEMAR_STRIPE_PRICE_MAKER=price_...
MEMAR_STRIPE_PRICE_PRO=price_...
MEMAR_STRIPE_PRICE_FARM=price_...
MEMAR_STRIPE_PRICE_SCALE=price_...

# License key (if self-activating)
MEMAR_LICENSE_KEY=
```

---

## 2. Docker (recommended)

```bash
cd /path/to/memar
docker-compose up -d
```

- Backend: http://localhost:9000
- Frontend: http://localhost:5173 (dev) or served from nginx in production


### Cloudflare Tunnel

```bash
cloudflared tunnel create memar
cloudflared tunnel route dns memar memar.yourdomain.com
# Add to ~/.cloudflared/config.yml:
#   ingress:
#     - hostname: memar.yourdomain.com
#       service: http://localhost:9000
cloudflared tunnel run memar
```

Set `MEMAR_PUBLIC_URL=https://memar.yourdomain.com` in `.env`, then restart:

```bash
docker compose restart memar
```

Register the Stripe webhook endpoint at:
`https://memar.yourdomain.com/stripe/webhook`

---

## 3. Bare-Metal (systemd)

```bash
# Install
sudo useradd -r -m -d /opt/memar memar
sudo cp -r . /opt/memar/current
sudo chown -R memar:memar /opt/memar
sudo python3 -m venv /opt/memar/current/backend/.venv
sudo /opt/memar/current/backend/.venv/bin/pip install -r /opt/memar/current/backend/requirements.txt

# Configure
sudo cp backend/.env /etc/memar.env
sudo chmod 600 /etc/memar.env
sudo chown memar:memar /etc/memar.env
sudo mkdir -p /var/lib/memar && sudo chown memar:memar /var/lib/memar

# Install service
sudo cp deploy/systemd/memar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now memar
```

Check logs:
```bash
journalctl -u memar -f
```

---

## 4. Stripe Setup

1. Create 4 products in Stripe dashboard: Maker ($19/mo), Pro ($49/mo), Farm ($199/mo), Scale ($499/mo)
2. Copy each monthly price ID → `.env` `MEMAR_STRIPE_PRICE_*`
3. Add webhook endpoint: `https://memar.yourdomain.com/stripe/webhook`
4. Select events: `checkout.session.completed`, `invoice.payment_failed`, `customer.subscription.deleted`
5. Copy webhook signing secret → `.env` `MEMAR_STRIPE_WEBHOOK_SECRET`

---

## 5. Health Check

```bash
curl http://localhost:9000/api/healthz
# {"status":"ok","version":"..."}
```

---

## 6. Upgrade

```bash
git pull
docker-compose down && docker-compose up -d --build
# or for bare-metal:
sudo systemctl restart memar
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Emails not sending | Verify SMTP vars; Gmail needs App Password not account password |
| Stripe webhooks failing | Check `MEMAR_STRIPE_WEBHOOK_SECRET` matches Stripe dashboard |
| JWT errors after restart | `MEMAR_JWT_SECRET` must be stable — don't regenerate in production |
| Port 9000 in use | Change `--port` in `memar.service` ExecStart and docker-compose ports |
