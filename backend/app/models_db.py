"""SQLAlchemy ORM table definitions for MEMAR."""

from sqlalchemy import (
    Column,
    Integer,
    Float,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class Team(Base):
    """Teams table for multi-tenant organization."""

    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    users = relationship("User", back_populates="team", cascade="all, delete-orphan")


class User(Base):
    """Users table with role-based access control."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="viewer")  # admin, operator, viewer
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # "local" | "oidc" | "ldap" — which method provisioned this account. SSO/LDAP
    # login only ever matches an existing row of the SAME provider (see
    # sso.py::_provision_and_issue); this is what stops an SSO login from
    # silently taking over a pre-existing local-password account (e.g. admin)
    # whose username happens to collide with an IdP-asserted email.
    auth_provider = Column(String(20), nullable=False, default="local", server_default="local")
    # True forces a password change before any protected route is reachable.
    # Set only for the shipped default admin/admin account; cleared on first change.
    must_change_password = Column(Boolean, default=False, nullable=False, server_default="0")
    # JSON list of enabled auth methods for this user: ["password", "passkey", "magic_link", "ldap", "oidc"]
    # NULL = all methods enabled (default). Empty list = user disabled (cannot login).
    enabled_auth_methods = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    team = relationship("Team", back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    webhooks = relationship("Webhook", back_populates="creator", cascade="all, delete-orphan")
    # NO delete-cascade: audit records outlive the user (user_id nulled on delete,
    # username retained) so deleting a user never erases their audit trail.
    audit_logs = relationship("AuditLog", back_populates="user")


class SSOSettings(Base):
    """Singleton row (id always 1) holding DB-editable SSO config.

    Every field is nullable and falls back to the matching MEMAR_* env var
    when unset (see sso.py::_resolve) — an existing env-var-only deployment
    keeps working unchanged. A non-null value here overrides the env var,
    letting an admin configure SSO live from Settings instead of editing
    the environment and restarting. oidc_client_secret is stored plaintext,
    same trust model as printer api_key in devices.yaml (host access is the
    boundary, not encryption-at-rest) — the admin-facing GET never returns
    it, only an oidc_client_secret_set boolean (see sso.py's redact helper).
    """

    __tablename__ = "sso_settings"

    id = Column(Integer, primary_key=True)
    oidc_issuer = Column(String(500), nullable=True)
    oidc_client_id = Column(String(255), nullable=True)
    oidc_client_secret = Column(String(500), nullable=True)
    oidc_redirect_uri = Column(String(500), nullable=True)
    ldap_server = Column(String(500), nullable=True)
    ldap_user_dn_template = Column(String(500), nullable=True)
    ldap_default_role = Column(String(50), nullable=True)
    sso_default_role = Column(String(50), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class RefreshToken(Base):
    """Refresh tokens table for JWT-based auth."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True)  # SHA-256 of opaque token
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")


class Webhook(Base):
    """Webhooks table for event delivery configuration."""

    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True)
    url = Column(String(2048), nullable=False)
    events = Column(JSON, nullable=False)  # JSON array of event names
    active = Column(Boolean, default=True, nullable=False)
    # Per-webhook signing secret (hex). Returned to the user ONCE at creation;
    # the receiver uses it to verify the X-MEMAR-Signature HMAC. Generated with
    # secrets.token_hex(32). nullable for rows created before this column existed.
    secret = Column(String(64), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    creator = relationship("User", back_populates="webhooks")


class FloorPlanLayout(Base):
    """Floor plan layout positions for devices."""

    __tablename__ = "floor_plan_layouts"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(255), nullable=False, unique=True)
    x = Column(Integer, default=0, nullable=False)
    y = Column(Integer, default=0, nullable=False)
    rotation = Column(Integer, default=0, nullable=False)  # degrees 0-360
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AuditLog(Base):
    """Audit log table for compliance and debugging."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(255), nullable=True)
    action = Column(String(255), nullable=False)  # e.g. "start_print", "add_device", "update_license"
    resource = Column(String(255), nullable=True)  # e.g. "printer:printer_id", "license"
    detail = Column(Text, nullable=True)  # JSON or free text detail
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="audit_logs")


class Branding(Base):
    """White-label branding (single row, id=1). Applied only when the license
    carries custom_branding; otherwise the app falls back to MEMAR defaults."""

    __tablename__ = "branding"

    id = Column(Integer, primary_key=True)  # always 1 — single row
    company_name = Column(String(255), nullable=True)
    logo_url = Column(String(2048), nullable=True)
    primary_color = Column(String(32), nullable=True)  # hex, e.g. #00a046
    support_email = Column(String(255), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class StripeCustomer(Base):
    """Stripe customer mapping for billing."""

    __tablename__ = "stripe_customers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    stripe_customer_id = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(200), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class WebAuthnCredential(Base):
    """WebAuthn/FIDO2 passkey credentials for passwordless login."""

    __tablename__ = "webauthn_credentials"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    credential_id = Column(Text, nullable=False, unique=True)  # base64url encoded
    public_key = Column(Text, nullable=False)  # COSE public key (base64url encoded)
    sign_count = Column(Integer, default=0, nullable=False)  # Cloning detection
    transports = Column(String(255), nullable=True)  # usb, ble, nfc, internal
    name = Column(String(255), nullable=True)  # User-friendly name, e.g., "MacBook Face ID"
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_used = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])


class WebAuthnChallenge(Base):
    """Temporary challenge storage for WebAuthn registration/authentication."""

    __tablename__ = "webauthn_challenges"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    challenge = Column(Text, nullable=False, unique=True)  # base64url encoded
    challenge_type = Column(String(20), nullable=False)  # "registration" or "authentication"
    expires_at = Column(DateTime, nullable=False)  # Usually now + 10 minutes
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])


class IssuedLicense(Base):
    """Issued licenses from Stripe checkout sessions."""

    __tablename__ = "issued_licenses"

    id = Column(Integer, primary_key=True)
    stripe_customer_id = Column(String(100), nullable=False, index=True)
    email = Column(String(200), nullable=False)
    tier = Column(String(30), nullable=False)  # maker, pro, farm, scale
    device_limit = Column(Integer, nullable=False)
    license_key = Column(Text, nullable=False)  # base64 encoded signed key
    stripe_session_id = Column(String(200), unique=True, nullable=False)
    issued_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    activated = Column(Boolean, default=False, nullable=False)
    activated_at = Column(DateTime, nullable=True)
    renewal_warning_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class SpoolLog(Base):
    """Spool depletion log — one row per print job completion."""

    __tablename__ = "spool_log"

    id = Column(Integer, primary_key=True)
    printer_id = Column(String(255), nullable=False, index=True)
    job_name = Column(String(512), nullable=True)
    filament_used_mm = Column(Integer, nullable=True)   # from Moonraker print_stats
    filament_used_g = Column(Integer, nullable=True)    # computed grams deducted
    spool_before_g = Column(Integer, nullable=True)     # spool_remaining_g before
    spool_after_g = Column(Integer, nullable=True)      # spool_remaining_g after
    material = Column(String(64), nullable=True)        # material at time of print
    source = Column(String(64), nullable=False, default="auto")  # 'auto' | 'manual'
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class StripeEventLog(Base):
    """Idempotency log for Stripe webhooks."""

    __tablename__ = "stripe_event_log"

    id = Column(Integer, primary_key=True)
    stripe_event_id = Column(String(100), nullable=False, unique=True, index=True)
    event_type = Column(String(100), nullable=False)
    processed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class WebhookDeliveryLog(Base):
    """Webhook delivery attempt log for debugging and retry."""

    __tablename__ = "webhook_delivery_log"

    id = Column(Integer, primary_key=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    attempt = Column(Integer, default=1, nullable=False)  # attempt number (1, 2, 3...)
    status_code = Column(Integer, nullable=True)  # HTTP status (200, 500, None if timeout)
    error = Column(Text, nullable=True)  # error message if failed
    delivered_at = Column(DateTime, nullable=True)  # when successfully delivered (NULL if failed)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


# --- Telemetry time-series tables -------------------------------------------
# Device IDENTITY lives in devices.yaml config (the single source of truth).
# These tables hold only TIME-SERIES history keyed by the config device_id
# string (no FK to a Device table — there is none, deliberately). The telemetry
# sampler (telemetry.py) writes them; analytics.py / coolant_models.py read them.

class FleetStatusLog(Base):
    """Periodic snapshot of each device's state — drives utilization/availability."""

    __tablename__ = "fleet_status_log"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    state = Column(String(50), nullable=False)   # idle, printing, running, error, offline
    online = Column(Boolean, default=False, nullable=False)


class JobLog(Base):
    """One row per completed/failed job — drives OEE trend + error analytics."""

    __tablename__ = "job_log"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(255), nullable=False, index=True)
    job_name = Column(String(512), nullable=True)
    status = Column(String(50), nullable=False)          # completed, failed, cancelled
    failure_reason = Column(String(255), nullable=True)
    oee = Column(Float, nullable=True)                    # composite OEE for the job, if computed
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True)
    duration_s = Column(Integer, nullable=True)


class SamplerLock(Base):
    """Single-row lease so exactly ONE process runs the telemetry sampler.

    Under `uvicorn --workers N` every worker would otherwise run its own sampler
    and write duplicate rows (skewing the very analytics they feed). A worker may
    sample only while it holds this lease; the lease is renewed each tick and can
    be taken over once stale, so a crashed holder doesn't stop sampling forever.
    """

    __tablename__ = "sampler_lock"

    id = Column(Integer, primary_key=True)  # always 1 — single row
    holder = Column(String(64), nullable=False)
    heartbeat_at = Column(DateTime, nullable=False)


class AnomalyAck(Base):
    """An acknowledged anomaly: one row == "(device_id, code) is acked".

    Anomalies themselves are ephemeral — recomputed every poll in
    fleet._collect_anomalies. This table is the only durable state: it suppresses
    a specific anomaly code for a specific device. The ack auto-clears (the row is
    pruned in fleet._apply_anomaly_acks) once the condition goes away, so a later
    recurrence of the same code re-alerts instead of staying silently acked.
    """

    __tablename__ = "anomaly_acks"
    __table_args__ = (UniqueConstraint("device_id", "code", name="uq_anomaly_ack_device_code"),)

    id = Column(Integer, primary_key=True)
    device_id = Column(String(255), nullable=False, index=True)
    code = Column(String(64), nullable=False)
    acked_at = Column(DateTime, server_default=func.now(), nullable=False)


class AlphaControlAck(Base):
    """One row == "this user has acknowledged the alpha-adapter liability
    warning for this device." Keyed per (user, device) rather than globally or
    per-license: a blanket ack would silently cover future alpha devices under
    a stale click, and per-action confirmation would throttle E-Stop, which the
    rest of this codebase treats as a safety bug. Never auto-cleared — the risk
    (unverified hardware bridge) doesn't go away like an anomaly condition does.
    """

    __tablename__ = "alpha_control_acks"
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_alpha_ack_user_device"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(255), nullable=False, index=True)
    acked_at = Column(DateTime, server_default=func.now(), nullable=False)


class WsTicket(Base):
    """Short-lived, single-use ticket authorizing ONE WebSocket connection.

    Closes the token-in-query-string leak: instead of putting the long-lived
    access JWT in the WS URL (where proxy/access logs capture it), the client
    first POSTs /api/ws/ticket (Bearer-authed) to mint one of these nonces, then
    connects with `?ticket=<nonce>`. The nonce is opaque, expires in ~30s, and is
    consumed (row deleted) on first use, so a leaked WS URL is worthless.

    Stored in the DB (not an in-process dict) for the same reason the telemetry
    sampler uses SamplerLock: under `uvicorn --workers N` the worker that mints
    the ticket may not be the one that handles the WS upgrade, so the store must
    be shared. Safe regardless of the current worker count.
    """

    __tablename__ = "ws_tickets"

    nonce = Column(String(64), primary_key=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)
    expires_at = Column(DateTime, nullable=False)


class MessagingIdentity(Base):
    """Links a platform-specific user ID to a MEMAR user for command authorization.

    A sender on Telegram/Slack/Discord/Mattermost/Matrix must have a row here
    before they can issue commands. The linked User's role gates each command.
    Admins create links via POST /api/admin/messaging/identities.
    """

    __tablename__ = "messaging_identities"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_messaging_identity"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(32), nullable=False)         # telegram|slack|discord|mattermost|matrix
    platform_user_id = Column(String(128), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User")


class PasswordResetToken(Base):
    """Single-use password reset tokens (15-minute TTL).

    Mirrors RefreshToken pattern: DB stores SHA-256 hash, email carries plaintext.
    """

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User")


class CNCMetricsLog(Base):
    """Time-series of CNC machine metrics — drives coolant + spindle analytics.

    NOTE: coolant_psi is nullable and is currently NEVER populated by any shipped
    adapter — protocol adapters expose `coolant_active` (on/off), not a pressure
    reading. coolant_psi exists for when a real pressure-sensor source is added;
    until then coolant-PSI analytics correctly report no_data. coolant_active and
    the spindle/feed fields ARE populated from live status.
    """

    __tablename__ = "cnc_metrics_log"

    id = Column(Integer, primary_key=True)
    device_id = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    coolant_psi = Column(Float, nullable=True)           # reserved for a pressure sensor source
    coolant_active = Column(Boolean, nullable=True)
    spindle_rpm = Column(Integer, nullable=True)
    feed_rate_mm_min = Column(Float, nullable=True)
    machine_state = Column(String(50), nullable=True)
    tool_id = Column(String(50), nullable=True)   # active tool, for tool-change counting


class FloorPlan3DCache(Base):
    """Cache of AI-generated isometric 3D floor-plan renders (Higgsfield).

    One row per unique fleet layout signature. A render is expensive (external
    paid API + ~1min latency), so it is generated once and cached: the signature
    (sha256 of device_count + sorted device_types + prompt_version) lets an
    unchanged fleet re-serve the same image instead of re-billing. status walks
    pending -> ready | failed; the poll endpoint drives the transition by
    querying the Higgsfield job (hf_job_id) and downloading result_url on
    completion. Bumping prompt_version invalidates every cached image at once.
    """

    __tablename__ = "floor_plan_3d_cache"

    id = Column(Integer, primary_key=True)
    fleet_id = Column(String(255), nullable=True)
    signature = Column(String(64), nullable=False, unique=True)  # sha256 hex
    hf_job_id = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending|ready|failed
    image_path = Column(String(512), nullable=True)
    prompt = Column(Text, nullable=True)
    prompt_version = Column(Integer, nullable=False, default=1)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    generated_at = Column(DateTime, nullable=True)
