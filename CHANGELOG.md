# Changelog

All notable changes to MEMAR are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed (adversarial audit, 2026-10-16)
- Browser setup could fail on a fresh install: with the pinned minimum FastAPI
  (0.115.12) the claim request body was read as a query parameter and every
  `POST /api/setup/claim` returned 422. Caught by running the suite in the
  hermetic CDE image with floor-pinned dependencies.
- Setup without a code (auto mode) is now only offered to private-network
  clients (LAN, loopback, tailnet). A public address always needs the setup
  code. The 10-minute window starts once per install (persisted in the data
  directory), not again on every restart.
- Native install no longer aborts when `BUILD_ID` is absent (it is not part
  of the public source); a build id is derived from git or the time.
- Licence renewal banner follows the key in force (newest activated, still
  valid). Re-issued monthly keys no longer surface a stale "ends in N days"
  warning, and a lapsed licence keeps a visible warning instead of going quiet.
- Device wizard: after a partial add, "Retry failed" re-adds the failed rows
  (it previously did nothing), rows already added no longer use up plan slots,
  and the finish screen lists every device added in the session.
- Settings: licence tier labels match the plans (Free 5 / Pro 40 /
  Enterprise 10,000).
- Setup code guessing: only wrong codes are counted (per client and in total),
  so a guesser is blocked for 15 minutes while the owner is never locked out by
  correct requests. The old limit counted every request.
- Printer names supplied by a device are text only, capped at 64 characters
  (control characters removed), on every path.
- One network scan at a time; a second request gets 429 instead of starting
  another sweep.
- Passwords longer than 72 bytes are refused (bcrypt ignores the rest), at
  setup and when an admin creates a user.
- Billing's renewal flag uses the banner's window (7 days online, 30 air-gap).
- Outgoing mail links use MEMAR_PUBLIC_URL through one helper.

### Added

- First run without configuration: `docker build -t memar:local . && docker run -p 8000:8000 -v memar-data:/app/data memar:local` starts with no environment variables. MEMAR creates and keeps its own signing key and prints a setup link (`docker logs memar`, the installer output, or `memar setup-link`).
- Browser setup of the first admin account. Policy `MEMAR_SETUP_MODE`: `auto` (default; no code needed for 10 minutes after the first start, then the setup code; private-network clients only), `open`, or `code` (default with an air-gap licence).
- `memar` command: `status`, `setup-link`, `reset-admin` (removes accounts, keeps devices and history). Works as `docker exec memar memar …` and `sudo memar …`.
- Optional licence key on the setup screen and `install.sh --license KEY` / `--license-file PATH`. A rejected key never blocks account creation.
- Device setup wizard: scans every Moonraker port 7125–7144 per host (KIAUH multi-instance), uses the printer names set in Mainsail/Fluidd, marks devices already added, adds several devices at once, respects the plan's device limit, shows the scanned subnet and lets you enter another, and no longer asks for a device ID.
- Container entrypoint makes `/app/data` writable and then runs as uid 10001 (or `MEMAR_UID`/`MEMAR_GID`), so host folders and volumes from older images work. `HEALTHCHECK` uses `/api/readyz`, which now checks the database. `scripts/uninstall.sh`.

### Changed

- There is no default admin/admin account any more. `MEMAR_JWT_SECRET` and `MEMAR_ADMIN_PASSWORD` are optional.
- The container listens on port 8000 (was 9000). All data, including logs and `devices.yaml`, lives in `/app/data`.
- `docker-compose.yml` pulls the published image; building from source moved to `docker-compose.build.yml`.

### Security

- Forgot-password never returns the reset link in the HTTP response; without email it is printed to the server log only.
- The network scan covers private (LAN) subnets only. The connection test accepts LAN, Tailscale/CGNAT (100.64.0.0/10) and loopback addresses; public addresses need `MEMAR_ALLOW_PUBLIC_DEVICES=true`.
- `devices.yaml` is written with mode 0600 (it can hold device API keys).

### Fixed

- Bundled fonts were blocked by the Content-Security-Policy (16 console errors per page load).
- Fleet dashboard settings did not load until a page reload after signing in.
- A log directory that is not writable no longer stops MEMAR from starting.
- `install.sh --docker` on Debian 13: the Docker CLI ships in the separate `docker-cli` package (only a Recommends of `docker.io`), so Docker was installed without the `docker` command. The installer now adds `docker-cli` and `ca-certificates`.
- `install.sh --docker` installs `curl` when it is missing. Without it the readiness check always failed and no setup link was shown.
- The installer finds the LAN address without iproute2 (minimal images), so setup links no longer say `localhost`.
- First-run and sign-in screens: a form taller than the window was pushed above the top of the screen, where it could not be scrolled to (the title was unreachable at 1366x768). The page now grows and scrolls instead. The light-theme background no longer fades from white to black.
- First-run screen: wider card, larger helper text, "✓ Filled in from your setup link" instead of Docker help when the code came from the link, a one-line "Paid plan? Add your license key" link, and clear license results that name the real "Free plan" button.
- Free plan: background requests for paid-only data no longer pop red "Feature 'oee' requires a paid plan." toasts; paid-feature messages use plain names.
- Monthly plans no longer show "license expires in 30 days" from the day they are activated. Online plans renew automatically and warn in their last 7 days; air-gap licences still warn 30 days ahead. The header shows "Free plan · Upgrade" / "Farm plan".
- Device wizard: Klipper printers found by the scan are ticked already, the scan result says how many devices were found, network ranges are shown as "addresses 192.168.1.x", and ports are shown only when one host runs several printers.

- Dependencies track the latest releases: `requirements.txt` uses minimum versions only (no upper caps); Dependabot config for pip, npm, cargo, Docker and Actions; weekly CI against the newest releases on Python 3.11–3.15 and Node LTS/current, plus the minimum versions, the installer on 4 distros, the Docker image and the Rust tools.
- `install.sh`: one-command installer for Debian/Ubuntu/Armbian, Fedora/RHEL, Arch, openSUSE and Alpine on x86_64/arm64/armv7. Native systemd install by default, `--docker` and `--no-service` modes, generated secrets, Klipper/Moonraker auto-discovery, fetches the current Node LTS or a standalone Python when the distro versions are too old.
- Password reset via email fallback and hardened forgot-password flow with token expiry and single-use enforcement.
- Settings and device controls reorganized into drawer panels.
- Design tokens and UI primitives: Badge, Button, Checkbox, Input, Select — all theme-token driven with WCAG-compliant states.
- Layout refinements across AnalyticsDashboard, CNCMetricsPanel, and CoolantMetricsGrid.
- Accessibility: ARIA live regions, visible focus rings, dark mode contrast pass.
- Comprehensive Settings drawer covering 25+ configuration categories (auth, notifications, integrations, appearance, telemetry, printers, coolant, floorplan, and more).
- Jog D-pad redesign with dedicated XY and Z home buttons, HOME ALL, and unit labels.
- History and file sorting: sort files by date, filament, and duration; consistent sort persistence across drawer sessions.
- WCAG 2.1 ARIA labels across drawer components and semantic modal landmarks.
- JSON-LD structured data and improved meta tags for SEO.
- Demo device photos and floorplan image registration for onboarding walkthroughs.
- Console history autocomplete and macro parameter editor.

### Changed

- Updated to current releases: FastAPI 0.143, Starlette 1.8, SQLAlchemy 2.1, Pydantic 2.14, Stripe 16, bcrypt 5, React 19, Vite 8, Recharts 3, TypeScript 7, three.js 0.186, Vitest 5. Docker images use `node:lts-slim`, `python:3-slim`, `rust:1-slim`.
- Passwords: `passlib` removed (unmaintained; broke on bcrypt 4.1+). bcrypt is called directly; existing hashes stay valid.
- Python 3.11+ required (the code uses `asyncio.timeout`); tested through Python 3.15.
- Removed the unused `tailwindcss` dependency and config (it was never wired into the build; built CSS is byte-identical).
- three.js and Recharts are now lazy-loaded with Suspense fallbacks, cutting initial bundle weight.
- Type-safety pass: removed `as any` casts across drawer state hooks; introduced typed keys `HistorySortKey`, `MotionIntent`, and `FileMetadataColumnKey`.
- UI polish: sizing consistency, responsive breakpoints, and contrast improvements across metric tiles and drawers.

### Fixed

- Docker image: a plain `docker run` (without the compose volumes) crashed at startup because `/app/logs` and the default DB path were not writable by the `memar` user. The image now creates `/app/logs` and `/app/data` for that user and defaults the DB and device config into `/app/data`.
- `datetime.utcnow()` (deprecated, slated for removal) replaced with `app.timeutil.utcnow()`, same naive-UTC values.
- Frontend build: `npm ci` now uses `--legacy-peer-deps` to match the lockfile; build no longer fails copying from `dist/` (Vite writes `frontend_dist/` directly).
- Tests: `ldap3` added to dev and optional requirements, so the 3 LDAP SSO tests run instead of skipping (822 passed, 0 skipped).
- systemd install: seeds `devices.example.yaml` (was a missing `printers.example.yaml`), keeps an existing `/etc/memar.env`, configurable port via `MEMAR_PORT`.

- Multiple TypeScript regressions in printerControlStore: missing annotations and incorrect `FileMetadataColumnKey` usage.
- Modal fixes across setup wizard, coolant, and floorplan drawers.
- Floorplan view-mode collapse and image-registration edge cases.
- CNC feedrate refusal handling and 3D-printer adapter reliability.
- Numerous smaller fixes across the backend and device status reporting.

### Security

- Forgot-password flow hardened: token expiry, single-use enforcement, and rate-limited email dispatch.

## [1.0.0] - 2026-07-02

First public release, licensed under the **GNU Affero General Public License v3.0
(AGPL-3.0)**. If you modify MEMAR and run the modified version as a network
service that other users interact with, the AGPL requires you to make your
modified source available to those users — see [LICENSE](LICENSE) for the full
terms. This does not affect normal self-hosted use of an unmodified install.

### Added

- **Fleet dashboard** — real-time status across mixed equipment (3D printers and CNC machines) in one view, with a floor-plan overlay for drag-drop device placement and live status visualization, and real-time telemetry over WebSocket.
- **18 machine adapters** — **6 supported** (Klipper/Moonraker, OctoPrint, Prusa Connect, Marlin, Duet, FluidNC) and **12 alpha** (including Bambu Lab, reverse-engineered) (generic MQTT, GRBL, LinuxCNC, Mach3, Mach4, OPC-UA, Sinumerik, Haas, Fanuc, Fadal, OpenPCB/OpenPnP), spanning FDM, SLA, IDEX, CNC mills/lathes/routers, laser, plasma, waterjet, vinyl cutters, pick-and-place, and wire EDM. The four CNC controllers Haas, Fanuc, Fadal, and Mach4 are **unverified against real hardware — emergency-stop is not guaranteed** and are pilot/roadmap only.
- **OEE analytics** — Availability × Performance × Quality, calculated per device and rolled up fleet-wide, with trend charts, job history, and per-machine breakdowns.
- **Role-based access control** — JWT-based auth with admin/operator/viewer roles. All mutating and control routes (jog, G-code, temperature, macros, queue, settings, etc.) require an authenticated admin or operator — previously some of these were reachable by any authenticated user, including the public demo/viewer token. Motion-initiating CNC commands (G-code, homing) are admin-only; emergency stop is available to both admin and operator so whoever's on the shop floor can hit it.
- **Licensing & billing** — Ed25519-signed offline license keys across free/maker/pro/farm/scale/workshop/business/enterprise tiers, an offline key-minting CLI for air-gapped deployments, Stripe checkout/upgrade/cancellation (requires your own Stripe account and price IDs; off by default), and proactive renewal-warning emails sent 30 days before a license expires. Air-gap and free-tier licenses never phone home.
- **SSO (beta)** — OIDC authorization-code login (with JWKS signature verification and nonce-based replay protection) and LDAP login, licensable per-instance. SSO/LDAP configuration (issuer, client credentials, LDAP server and DN template, default roles) can now be set live from the admin panel's Settings screen instead of requiring an environment-variable edit and restart.
- **Admin panel** — user management (create/suspend/reset), role assignment, white-label branding controls, and a full audit log (actor, action, timestamp) for compliance review.
- **Password reset** — self-service, time-limited (15-minute) reset tokens, plus admin-initiated reset with a forced password change on next login. The default `admin`/`admin` account itself requires a password change before any protected route is reachable.
- **Messaging hub** — alert fan-out to seven channels (ntfy, generic webhook, Telegram, Slack, Discord, Mattermost, Matrix), including bidirectional chat commands on Telegram, Matrix, and Mattermost (and Slack/Discord with bot tokens).
- **Webhook events** — outbound `printer.error`, `printer.complete`, `printer.offline`, and related events, HMAC-signed with delivery logs, for integrating MEMAR into external systems.
- **Light/dark theming** across the app, plus mobile-responsive layout and accessibility fixes (focus handling, keyboard navigation).

### Fixed

- Numerous dashboard, floor-plan, and fleet-matrix correctness issues found during pre-launch hardening (OEE-percentage rendering, maintenance-due counts, telemetry backfill/dedup, light-mode contrast throughout the app).
- Log volume was capped (rotating file handler, WARNING-level thresholds on noisy dependencies) to stop long-running deployments from filling disk.

### Security

- **SSO/LDAP account-takeover:** signing in via SSO or LDAP could match and log into a pre-existing local-password account (including `admin`) if the username or email happened to collide. Fixed — SSO/LDAP sign-in now only matches an account provisioned by that same method, and returns a conflict error instead of logging in when a collision occurs.
- **LDAP empty-password bypass:** an LDAP bind with an empty password authenticates nothing per spec, but some directory servers return success for it anyway. MEMAR now rejects empty-password LDAP sign-in before a bind is ever attempted, and escapes LDAP usernames before using them in a bind DN. Unverified OIDC email claims are no longer trusted as an account identity.
- **Route authorization:** all mutating/control routes are now explicitly role-gated to admin or operator; a subset were previously reachable with only a valid session, including via the public read-only demo login. A related SSRF-adjacent issue in a device settings field (Spoolman URL) was closed the same way.
- Bumped `python-jose` 3.3.0 → 3.5.0 (security fixes for JWT handling).
- CORS was tightened from a wildcard method list to an explicit allow-list; rate limiting (previously silently disabled if the dependency was missing on a fresh install) is now enforced on login, password change, and token refresh.
