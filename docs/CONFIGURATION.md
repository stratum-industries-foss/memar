# MEMAR Configuration Reference

All configuration is via environment variables. Only `MEMAR_JWT_SECRET` is
required in production; everything else has safe defaults.

## Core

| Variable | Default | Notes |
|---|---|---|
| `MEMAR_JWT_SECRET` | (random in dev — **required in prod**) | Fixed secret; otherwise sessions break across restarts/workers. |
| `MEMAR_ADMIN_USER` | `admin` | Seed admin username (created on first run). |
| `MEMAR_DB_PATH` | local sqlite | Database path. |
| `MEMAR_PUBLIC_URL` | `http://localhost:8000` | Public base URL for billing + SSO redirects. **Must be the URL users actually reach** — `http://localhost:8000` for the default Docker port-map (`8000:9000`), or your real domain (e.g. `https://memar.example.com`). *Not* the internal container port `9000`, or OIDC redirects break. |

## Licensing

| Variable | Default | Notes |
|---|---|---|
| `MEMAR_LICENSE_KEY` | (none → Free tier) | Your signed license key. Paste it once. |
| `MEMAR_LICENSE_HEARTBEAT_URL` | `""` (empty, disabled) | The instance periodically checks your subscription and **auto-refreshes** the key — so renewals never need a manual re-paste. Set to `""` to disable (e.g. air-gap). |

- **Renewals are automatic** while the heartbeat is enabled and the subscription is active — the key's expiry is pushed forward each period.
- If the heartbeat endpoint is unreachable, the current key keeps working until its own embedded expiry (a grace window), then drops to Free.
- **Air-gap keys** (annual term, **billed monthly** — a 12-month commitment) skip the heartbeat entirely (zero outbound calls). The offline key stays valid for the paid term; **renew each year by pasting a fresh key** (re-issued on renewal). Not a perpetual or one-time key.

## Email alerts (Maker+)

| Variable | Default | Notes |
|---|---|---|
| `MEMAR_ALERT_EMAILS` | (none) | Comma-separated recipients for equipment alerts (device error/offline). |
| `MEMAR_SMTP_HOST` / `MEMAR_SMTP_PORT` | `smtp.gmail.com` / `587` | SMTP server. |
| `MEMAR_SMTP_USER` / `MEMAR_SMTP_PASSWORD` | (none) | SMTP auth (also used for license emails). |
| `MEMAR_SMTP_FROM` | = `MEMAR_SMTP_USER` | From address. |

Alerts are debounced (one email per device per 15 min).

## SSO (any paid tier)

Login buttons appear automatically once configured **and** licensed.

### OIDC (Google, Okta, Azure AD, Auth0, …)
| Variable | Notes |
|---|---|
| `MEMAR_OIDC_ISSUER` | e.g. `https://accounts.google.com` |
| `MEMAR_OIDC_CLIENT_ID` | OAuth client id |
| `MEMAR_OIDC_CLIENT_SECRET` | OAuth client secret |
| `MEMAR_OIDC_REDIRECT_URI` | must equal `<MEMAR_PUBLIC_URL>/api/auth/sso/oidc/callback` and match the IdP config |

### LDAP / Active Directory
| Variable | Notes |
|---|---|
| `MEMAR_LDAP_SERVER` | e.g. `ldap://ldap.example.com` |
| `MEMAR_LDAP_USER_DN_TEMPLATE` | e.g. `uid={username},ou=people,dc=example,dc=com` |
| `MEMAR_LDAP_DEFAULT_ROLE` | role for LDAP users (default `viewer`) |

> LDAP requires the `ldap3` package in your runtime (included in the Nix env / `pip install ldap3`).

### SSO common
| Variable | Default | Notes |
|---|---|---|
| `MEMAR_SSO_DEFAULT_ROLE` | `viewer` | Role assigned to newly-provisioned SSO users. |

## White-label branding (any paid tier)

No env var — set via **Admin → Branding** in the UI (or `PUT /api/admin/branding`):
company name, logo URL, primary colour, support email. Applied to the app header,
login screen, tab title, and alert emails. Falls back to MEMAR defaults if the
license lacks `custom_branding`.

## Audit log (any paid tier)

No configuration — security events (logins, user/role changes, license activations)
are recorded automatically and viewable at **Admin → Audit log** (or `GET /api/admin/audit`).
