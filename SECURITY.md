# Security Policy

## Reporting a Vulnerability

Email **info@stratum.industries** with subject "MEMAR Security Report". Do not open a public GitHub issue for security vulnerabilities.

Expected response: within 48 hours. We will provide a patch timeline and credit researchers in the release notes (unless you prefer to remain anonymous).

## Safe Harbor

We consider good-faith security research to be authorized, not an attack, and we will not pursue legal action (including under the CFAA, DMCA anti-circumvention provisions, or similar state-law analogs) or refer you to law enforcement for that research, provided you:

- Make a good-faith effort to avoid privacy violations, data destruction, and service disruption — no exploitation beyond what's needed to demonstrate a finding, no automated scanning that degrades the service for other users.
- Only interact with accounts and data you own, or that you have explicit permission to test.
- Report findings promptly through the channel above, and don't publicly disclose before we've had a reasonable fix window (see Responsible Disclosure below).

This commitment covers MEMAR's own code and infrastructure controlled by Stratum Industries. It doesn't extend to third-party services we integrate with (e.g. Stripe) — check their own safe-harbor policies separately.

We're a solo-founder company. This is a legal-non-retaliation commitment, not a bug bounty program — we don't currently offer paid rewards or a formal SLA beyond the acknowledgment window above.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✅        |

## Hardening Guide

MEMAR is a self-hosted application. Network exposure and secret management are your responsibility.

**JWT secret**
Generate with `openssl rand -hex 32`. Never reuse across deployments. Set as `MEMAR_JWT_SECRET`.

**Admin credentials**
The default `admin`/`admin` account requires a mandatory password change on first login — enforced server-side. Do not skip this step.

**Network exposure**
Bind behind a reverse proxy (Caddy, nginx, Traefik). Do not expose port 9000 directly to the internet. Use HTTPS via your proxy.

**SMTP credentials**
Use an app-specific password, not your main account password. Set as `MEMAR_SMTP_PASSWORD`.

**Stripe keys**
`MEMAR_STRIPE_WEBHOOK_SECRET` should only be set on a backend that receives Stripe webhooks directly. If you use the Cloudflare license worker (the default setup), leave this unset on your MEMAR instance.

**License private key**
`MEMAR_LICENSE_PRIVATE_KEY` is only required on the key-issuing instance. Do not set it on customer deployments.

**Database backups**
Back up `/app/data/memar.db` regularly. The `memar_data` Docker volume persists the database across container restarts.

**Preflight check**
Run `python backend/scripts/preflight.py` before deploying to catch missing required env vars.

## Responsible Disclosure

We ask for private initial disclosure before any public post, and reasonable time to release a patch — **90 days** from your report by default, unless we agree in writing to a different timeline (e.g. the fix needs more time, or you're fine waiting longer). We commit to acknowledging reports within 48 hours and keeping you informed of progress.
