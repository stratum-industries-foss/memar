# Changelog

All notable changes to MEMAR are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

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

- three.js and Recharts are now lazy-loaded with Suspense fallbacks, cutting initial bundle weight.
- Type-safety pass: removed `as any` casts across drawer state hooks; introduced typed keys `HistorySortKey`, `MotionIntent`, and `FileMetadataColumnKey`.
- UI polish: sizing consistency, responsive breakpoints, and contrast improvements across metric tiles and drawers.

### Fixed

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
