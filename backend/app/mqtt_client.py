"""MQTT machine adapters for MEMAR.

The WIRED path is the push→poll bridge adapters — `MQTTPollingAdapter` (generic)
and `BambuPollingAdapter` (Bambu LAN). The protocol factory (`fleet._build_client`)
returns these. Each runs a background subscribe loop, caches the latest report, and
exposes the *polled* adapter contract (`async get_status()` / `async disconnect()`)
that the fleet factory and `_generic_status_to_fleet` consume:

  - Generic:  subscribes to "machines/{printer_id}/status" JSON topics.
  - Bambu:    "device/{serial}/report", Bambu-specific payload schema, LAN TLS.

aiomqtt is OPTIONAL (see requirements-optional.txt). When it is not installed the
bridge degrades to an offline status with a clear message — it never raises, so a
missing dependency cannot blank the whole fleet dashboard.

`MQTTMachineClient` / `BambuMQTTClient` below are an earlier push-callback scaffold,
NOT wired anywhere (the factory uses the bridge adapters). They are retained only as
reference for the raw subscribe/normalize shapes and may be removed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable

from .device_url import assert_safe_device_url

logger = logging.getLogger(__name__)

# If no MQTT report arrives within this window, the bridge reports the device
# offline (stale) rather than serving an indefinitely old snapshot.
_STALE_AFTER_SECONDS = 120


class MQTTMachineClient:
    """UNUSED legacy scaffold (not wired — see module docstring). Generic MQTT
    subscriber that feeds machine status into MEMAR.

    Usage:
        client = MQTTMachineClient("mqtt://broker:1883", printer_id, on_status)
        await client.connect()
        # Runs in background — calls on_status(dict) on each message
        await client.disconnect()
    """

    def __init__(
        self,
        broker_url: str,
        printer_id: str,
        on_status: Callable[[dict], None],
        topic_pattern: str = "machines/{id}/status",
    ):
        self.broker_url = broker_url
        self.printer_id = printer_id
        self.on_status = on_status
        self.topic = topic_pattern.format(id=printer_id)
        self._task: asyncio.Task | None = None
        self._running = False

    async def connect(self) -> None:
        try:
            import aiomqtt  # type: ignore
        except ImportError:
            logger.warning("aiomqtt not installed — MQTT protocol unavailable. pip install aiomqtt")
            return
        self._running = True
        self._task = asyncio.create_task(self._subscribe_loop(aiomqtt))

    async def disconnect(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _subscribe_loop(self, aiomqtt) -> None:
        host, port = _parse_broker(self.broker_url)
        while self._running:
            try:
                async with aiomqtt.Client(host, port) as client:
                    await client.subscribe(self.topic)
                    async for msg in client.messages:
                        if not self._running:
                            break
                        try:
                            payload = json.loads(msg.payload)
                            self.on_status(self._normalize(payload))
                        except Exception as e:
                            logger.debug("MQTT payload parse error: %s", e)
            except Exception as e:
                logger.warning("MQTT connection lost (%s), retrying in 5s: %s", self.broker_url, e)
                await asyncio.sleep(5)

    def _normalize(self, payload: dict) -> dict:
        """Default mapping — subclasses override for device-specific schemas."""
        return {
            "online": True,
            "state": payload.get("state", "idle"),
            "progress": payload.get("progress"),
            "nozzle_temperature": payload.get("nozzle_temp"),
            "bed_temperature": payload.get("bed_temp"),
            "filename": payload.get("filename"),
        }


class BambuMQTTClient(MQTTMachineClient):
    """UNUSED legacy scaffold (not wired — see module docstring; the wired Bambu
    path is BambuPollingAdapter). Bambu Labs MQTT client (unofficial API).

    Supports:
    - Local: bambulabs.local:8883 (TLS, auth with access_code)
    - Cloud: mqtt.bambulab.com:8883

    printer_id = serial number (e.g. "01P0A1B234567890")
    api_key    = access_code from Bambu Handy app or Bambu Studio
    """

    BAMBU_CLOUD_HOST = "mqtt.bambulab.com"
    BAMBU_CLOUD_PORT = 8883

    def __init__(
        self,
        serial: str,
        access_code: str,
        username: str,
        on_status: Callable[[dict], None],
        local_ip: str | None = None,
        ca_file: str | None = None,
        insecure_tls: bool = False,
    ):
        topic = f"device/{serial}/report"
        broker = f"mqtts://{local_ip}:8883" if local_ip else \
                 f"mqtts://{self.BAMBU_CLOUD_HOST}:{self.BAMBU_CLOUD_PORT}"
        super().__init__(broker, serial, on_status, topic_pattern=topic)
        self.serial = serial
        self.access_code = access_code
        self.username = username
        self.ca_file = ca_file
        self.insecure_tls = insecure_tls

    async def connect(self) -> None:
        try:
            import aiomqtt  # type: ignore
        except ImportError:
            logger.warning("aiomqtt not installed — Bambu MQTT unavailable")
            return
        self._running = True
        self._task = asyncio.create_task(self._bambu_loop(aiomqtt))

    async def _bambu_loop(self, aiomqtt) -> None:
        host, port = _parse_broker(self.broker_url)
        while self._running:
            try:
                async with aiomqtt.Client(
                    host, port,
                    username=self.username,
                    password=self.access_code,
                    tls_context=_tls_context(self.ca_file, self.insecure_tls),
                ) as client:
                    await client.subscribe(self.topic)
                    async for msg in client.messages:
                        if not self._running:
                            break
                        try:
                            payload = json.loads(msg.payload)
                            self.on_status(self._normalize(payload))
                        except Exception as e:
                            logger.debug("Bambu payload parse error: %s", e)
            except Exception as e:
                logger.warning("Bambu MQTT disconnected, retrying: %s", e)
                await asyncio.sleep(10)

    def _normalize(self, payload: dict) -> dict:
        """Map Bambu's report payload to MEMAR's status schema."""
        return _normalize_bambu(payload)


def _normalize_bambu(payload: dict) -> dict:
    """Map a Bambu `device/{serial}/report` payload to MEMAR's status schema.

    Bambu nests the print state under the `print` key.

    ASSUMPTIONS (reverse-engineered, UNVERIFIED without real Bambu hardware — may
    shift across firmware):
      - `mc_remaining_time` is in MINUTES → ×60 for MEMAR's `eta_seconds`.
      - `mc_percent` is a 0–100 progress scale.
      - `*_temper` / `*_target_temper` are °C.
      - `gcode_state` ∈ {RUNNING, PAUSE, FAILED, FINISH, IDLE, PREPARE, SLICING}.
      - AMS material at `ams.ams[0].tray[0].tray_type`.
    If a real printer reports different units/keys, values will be silently wrong —
    confirm against hardware before trusting these numbers (see docs/BAMBU_MQTT.md).
    """
    p = payload.get("print", {}) or {}
    remaining_min = p.get("mc_remaining_time")
    ams = p.get("ams")
    ams_material = None
    if isinstance(ams, dict):
        try:
            ams_material = ams.get("ams", [{}])[0].get("tray", [{}])[0].get("tray_type")
        except (IndexError, AttributeError, TypeError):
            ams_material = None
    return {
        "online": True,
        "state": _map_bambu_state(p.get("gcode_state", "IDLE")),
        "progress": p.get("mc_percent"),
        "nozzle_temperature": p.get("nozzle_temper"),
        "nozzle_target": p.get("nozzle_target_temper"),
        "bed_temperature": p.get("bed_temper"),
        "bed_target": p.get("bed_target_temper"),
        "filename": p.get("subtask_name") or p.get("gcode_file"),
        "eta_seconds": remaining_min * 60 if isinstance(remaining_min, (int, float)) else None,
        "layer_num": p.get("layer_num"),
        "total_layers": p.get("total_layer_num"),
        "ams_material": ams_material,
    }


def _normalize_generic(payload: dict, mapping: dict | None = None) -> dict:
    """Map a generic MQTT status payload to MEMAR's status schema.

    With a `mapping` ({memar_status_key: payload_key}) the device's own field
    names are pulled into the MEMAR keys MEMAR understands (state, progress,
    nozzle_temperature, bed_temperature, filename). Without it, a fixed default
    schema is assumed (state/progress/nozzle_temp/bed_temp/filename) — a SCAFFOLD
    that only fits a device already publishing those exact keys.
    """
    if mapping:
        def pick(memar_key, default=None):
            src = mapping.get(memar_key)
            return payload.get(src, default) if src else default
        return {
            "online": True,
            "state": pick("state", "idle"),
            "progress": pick("progress"),
            "nozzle_temperature": pick("nozzle_temperature"),
            "bed_temperature": pick("bed_temperature"),
            "filename": pick("filename"),
        }
    return {
        "online": True,
        "state": payload.get("state", "idle"),
        "progress": payload.get("progress"),
        "nozzle_temperature": payload.get("nozzle_temp"),
        "bed_temperature": payload.get("bed_temp"),
        "filename": payload.get("filename"),
    }


def _map_bambu_state(s: str) -> str:
    return {"RUNNING": "printing", "PAUSE": "paused", "FAILED": "error",
            "FINISH": "ready", "IDLE": "ready", "PREPARE": "printing",
            "SLICING": "printing"}.get(s, "idle")


def _parse_broker(url: str) -> tuple[str, int]:
    """Parse mqtts://host:port or mqtt://host:port into (host, port)."""
    url = url.replace("mqtts://", "").replace("mqtt://", "")
    if ":" in url:
        host, port_s = url.rsplit(":", 1)
        return host, int(port_s)
    return url, 1883


def _resolve_local_host(host: str) -> tuple[bool, str | None]:
    """Classify ``host`` for LAN-safe (CERT_NONE) TLS and, when possible, return a
    concrete private IP to PIN the connection to.

    Returns ``(is_local, pinned_ip)``:

    - ``is_local`` — True if host is a private/loopback/link-local address, i.e.
      safe to use with TLS verification disabled (the LAN access code never leaves
      the LAN). IP literals are checked directly. A hostname is resolved and ALL of
      its addresses must be private/loopback/link-local; if even one is public the
      host is rejected. This closes the prior hole where a bare single-label name
      got a free pass via ``"." not in h`` — with a DNS search domain such a name
      resolves to a routable public IP, which would have sent the access code over
      unverified TLS to an arbitrary host. Unresolvable ``.local`` mDNS names are
      link-local by definition and remain allowed; any other unresolvable name is
      rejected (fail closed).

    - ``pinned_ip`` — a concrete private IPv4 to connect to INSTEAD of re-resolving
      the hostname, set ONLY when ``host`` is a DNS name that resolved entirely to
      private addresses. This closes a TOCTOU gap: paho/aiomqtt re-resolves the
      hostname at connect time, so a name that flips private→public between this
      guard and the connect could otherwise send the access code over unverified
      TLS to a public host. Pinning the already-validated IP removes the second
      lookup. It is None (nothing to pin) for:
        * IP literals — already concrete, connect to the literal as-is;
        * ``localhost`` — always loopback, can't flip to public;
        * ``.local``/unresolvable-but-allowed — link-local by definition and often
          not resolvable here (needs avahi); can't pin what won't resolve;
        * IPv6-only private names — left on the hostname (see residual note below).
      Only the first IPv4 address is pinned to avoid IPv6 scope-id ambiguity; the
      all-private check above still validates every resolved address either way, so
      an IPv6-only private name stays allowed but connects via hostname (a narrow
      residual TOCTOU that requires an IPv6-only private DNS name).
    """
    import ipaddress
    import socket

    h = (host or "").strip().lower()
    if not h:
        return False, None
    try:
        ip = ipaddress.ip_address(h)
        return (ip.is_private or ip.is_loopback or ip.is_link_local), None
    except ValueError:
        pass  # not an IP literal — resolve and check the concrete address(es)

    if h == "localhost":
        return True, None
    try:
        addrs = socket.getaddrinfo(h, None)
    except socket.gaierror:
        # mDNS (.local) is link-local by definition and often isn't resolvable
        # here without avahi; allow only that suffix. Everything else fails closed.
        return h.endswith(".local"), None
    if not addrs:
        return h.endswith(".local"), None
    pinned: str | None = None
    for family, _type, _proto, _canon, sockaddr in addrs:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False, None  # unparseable resolved address — fail closed
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            return False, None  # any public address → deny CERT_NONE
        if pinned is None and family == socket.AF_INET:
            pinned = sockaddr[0]  # pin the first private IPv4 we resolved
    return True, pinned


def _is_local_host(host: str) -> bool:
    """True if host is a private/loopback/link-local address — i.e. safe to use
    with TLS verification disabled. Thin wrapper over :func:`_resolve_local_host`
    (kept for callers/tests that only need the boolean)."""
    return _resolve_local_host(host)[0]


def _tls_context(ca_file: str | None = None, insecure: bool = False):
    """Build TLS context. Provide ca_file for self-signed certs, or
    set insecure=True only in isolated dev environments (not production)."""
    import ssl
    ctx = ssl.create_default_context(cafile=ca_file)
    if insecure:
        # Only for dev/isolated networks. Never use in production.
        logger.warning("TLS verification disabled — do not use in production")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ── Push→poll bridge adapters ───────────────────────────────────────────────
#
# The fleet factory (`_build_client`) is synchronous and the status path polls
# `await client.get_status()`. MQTT is push-based, so these adapters run a
# background subscribe loop, cache the most recent normalized report, and serve
# it on demand. The loop is started lazily on the first `get_status()` call
# (which is async) because the factory itself cannot await.


class _MQTTPollingBase:
    """Base push→poll bridge. Subclasses define broker/topic/normalize/connect."""

    stale_after = _STALE_AFTER_SECONDS
    reconnect_delay = 5  # seconds between reconnect attempts after a loop error

    def __init__(self, printer) -> None:
        self.printer = printer
        self._latest: dict | None = None
        self._last_ts: float | None = None
        self._started = False
        self._task: asyncio.Task | None = None
        # Set by the constructor (bad config) or _ensure_started (missing aiomqtt).
        # When set, get_status() reports offline with this message and never starts
        # a loop — a misconfigured device only takes itself offline.
        self._fatal: str | None = None

    # ── subclass hooks ──
    def _build_topic(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def _make_client(self, aiomqtt):  # pragma: no cover - overridden
        raise NotImplementedError

    def _normalize(self, payload: dict) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    async def _on_connected(self, client) -> None:
        """Hook after subscribe (e.g. Bambu pushall). Default: no-op."""
        return None

    # ── machinery ──
    def _on_message(self, payload: dict) -> None:
        self._latest = self._normalize(payload)
        self._last_ts = time.monotonic()

    async def _ensure_started(self) -> None:
        if self._started:
            return
        # Set the guard BEFORE the first await so concurrent get_status() calls
        # from the fleet gather can never double-start the subscribe loop.
        self._started = True
        if self._fatal:
            return
        try:
            import aiomqtt  # type: ignore  # noqa: F401
        except ImportError:
            self._fatal = (
                f"Protocol '{self.printer.protocol.value}' needs the optional "
                "aiomqtt package — run: pip install aiomqtt"
            )
            logger.warning(self._fatal)
            return
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        import aiomqtt  # type: ignore

        topic = self._build_topic()
        while True:
            try:
                async with self._make_client(aiomqtt) as client:
                    await client.subscribe(topic)
                    await self._on_connected(client)
                    async for msg in client.messages:
                        try:
                            self._on_message(json.loads(msg.payload))
                        except Exception as e:  # noqa: BLE001
                            logger.debug("MQTT payload parse error (%s): %s", self.printer.id, e)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "MQTT loop for %s lost (%s); reconnecting in %ss",
                    self.printer.id, e, self.reconnect_delay,
                )
                await asyncio.sleep(self.reconnect_delay)

    async def get_status(self) -> dict:
        await self._ensure_started()
        if self._fatal:
            return {"online": False, "state": "offline", "state_message": self._fatal}
        if self._latest is None:
            return {
                "online": False,
                "state": "offline",
                "state_message": "Waiting for first MQTT report…",
            }
        age = time.monotonic() - (self._last_ts or 0.0)
        if age > self.stale_after:
            return {
                **self._latest,
                "online": False,
                "state": "offline",
                "state_message": f"No MQTT report in {int(age)}s (stale)",
            }
        return self._latest

    async def disconnect(self) -> dict:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
        self._task = None
        self._started = False
        return {"ok": True}


class MQTTPollingAdapter(_MQTTPollingBase):
    """Generic MQTT bridge.

    SCAFFOLD — not a turnkey integration. Subscribes to the fixed topic
    ``machines/{printer_id}/status`` on the broker given by ``base_url`` and maps a
    fixed default JSON schema (``state``/``progress``/``nozzle_temp``/``bed_temp``/
    ``filename``). There is no per-device topic or field-mapping config yet, so a
    device publishing a different topic/schema will appear **online with mostly
    null fields** rather than erroring — it cannot validate that it understood the
    payload. A real integration needs configurable topic + field mapping
    (follow-up: add ``mqtt_topic`` / ``mqtt_field_mapping`` to PrinterConfig).
    Bambu printers must use BambuPollingAdapter, not this.
    """

    def __init__(self, printer) -> None:
        super().__init__(printer)
        self._broker = printer.base_url or "mqtt://localhost:1883"
        # Validate broker URL for SSRF (convert mqtt:// to http:// for validation)
        broker_for_check = self._broker.replace("mqtt://", "http://").replace("mqtts://", "https://")
        assert_safe_device_url(broker_for_check)  # LAN broker: block metadata/link-local, allow RFC1918
        self._topic = (getattr(printer, "mqtt_topic", None) or "").strip()
        self._mapping = getattr(printer, "mqtt_field_mapping", None) or {}

    def _build_topic(self) -> str:
        # Configurable topic; falls back to the default convention.
        return self._topic or f"machines/{self.printer.id}/status"

    def _make_client(self, aiomqtt):
        host, port = _parse_broker(self._broker)
        return aiomqtt.Client(host, port)

    def _normalize(self, payload: dict) -> dict:
        return _normalize_generic(payload, self._mapping)


class BambuPollingAdapter(_MQTTPollingBase):
    """Bambu Lab printers over LOCAL MQTT (LAN mode).

    Uses the unofficial, reverse-engineered Bambu API. The connection parameters
    (port 8883, username 'bblp', self-signed-cert TLS) AND the payload schema are
    all reverse-engineered and can shift across Bambu firmware — confirm against
    real hardware (docs/BAMBU_MQTT.md). Config (PrinterConfig fields):
      base_url → printer LAN IP/host (TLS MQTT on :8883). MUST be a local address.
      serial   → printer serial number (the MQTT device id and topic)
      api_key  → LAN access code (Bambu Handy / Bambu Studio → Settings)
    The LAN username is assumed to be the fixed value 'bblp'. TLS verification is
    disabled because Bambu's LAN broker presents a self-signed cert — so to avoid
    leaking the access code, this adapter REFUSES to connect to a non-local host.
    """

    BAMBU_PORT = 8883
    BAMBU_LAN_USER = "bblp"

    def __init__(self, printer) -> None:
        super().__init__(printer)
        self._serial = (getattr(printer, "serial", None) or "").strip()
        self._access = printer.api_key or ""
        self._host = _parse_broker(printer.base_url)[0] if printer.base_url else ""
        # Host actually dialed by _make_client. Defaults to the configured host;
        # when the host is a DNS name that resolves entirely to private IPs we pin
        # the resolved IP here so aiomqtt does NOT re-resolve at connect time (a
        # TOCTOU where the name could flip private→public and leak the access code
        # over unverified TLS). Resolution is done lazily in the success branch
        # below so a missing serial/host/access still short-circuits without a DNS
        # lookup.
        self._connect_host = self._host
        if not self._serial:
            self._fatal = "Bambu adapter needs 'serial' set to the printer serial number"
        elif not self._host:
            self._fatal = "Bambu adapter needs base_url set to the printer's LAN IP/host"
        elif not self._access:
            self._fatal = "Bambu adapter needs api_key set to the LAN access code"
        else:
            local, pinned = _resolve_local_host(self._host)
            if not local:
                # Insecure TLS (no cert verification) + the LAN access code must
                # never be sent to an arbitrary remote host — that would leak the
                # credential.
                self._fatal = (
                    f"Bambu adapter refuses non-local host '{self._host}': LAN mode "
                    "disables TLS verification, so the access code is only sent to a "
                    "private/loopback/.local address. Use the printer's LAN IP."
                )
            elif pinned:
                # Pin the validated private IP (IP literals and .local stay on
                # self._host, which is already concrete / link-local).
                self._connect_host = pinned

    def _build_topic(self) -> str:
        return f"device/{self._serial}/report"

    def _make_client(self, aiomqtt):
        return aiomqtt.Client(
            self._connect_host,
            self.BAMBU_PORT,
            username=self.BAMBU_LAN_USER,
            password=self._access,
            tls_context=_tls_context(insecure=True),
        )

    async def _on_connected(self, client) -> None:
        # Bambu emits a full report only on request; trigger one so we don't wait
        # for the next periodic/delta push. The exact command body is reverse-
        # engineered and UNVERIFIED without hardware — if the printer connects but
        # no report ever arrives (get_status stays "Waiting…" then goes stale), the
        # pushall body/topic is the first thing to check against this log line.
        body = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}})
        try:
            await client.publish(f"device/{self._serial}/request", body)
            logger.debug("Bambu pushall sent to %s: %s", self.printer.id, body)
        except Exception as e:  # noqa: BLE001
            logger.debug("Bambu pushall request failed (%s): %s", self.printer.id, e)

    def _normalize(self, payload: dict) -> dict:
        return _normalize_bambu(payload)
