"""Coolant-alert evaluation + Slack no-op tests.

Covers the data-driven once-fn (evaluate_coolant_alerts_once), the no-PSI-data
skip path (the common case today — coolant_psi is NULL until a pressure source
exists), and the Slack send_alert graceful no-op when MEMAR_SLACK_WEBHOOK_URL is
unset. All outbound httpx is mocked so no real network is touched.

Seeding mirrors test_telemetry: depend on `client` (builds the in-memory DB) and
write rows via AsyncSessionLocal. Device identity comes from config, so we point
get_config() at a temp devices.yaml containing CNC machines.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import yaml


@pytest_asyncio.fixture
async def cnc_config(tmp_path, monkeypatch):
    """Point get_config() at a temp config with CNC + non-CNC devices."""
    import app.config as cfgmod

    cfg = {
        "printers": [
            {"id": "mill1", "name": "Mill One", "base_url": "http://10.0.0.1",
             "enabled": True, "machine_type": "cnc_mill"},
            {"id": "lathe1", "name": "Lathe One", "base_url": "http://10.0.0.2",
             "enabled": True, "machine_type": "cnc_lathe"},
            {"id": "router1", "name": "Router One", "base_url": "http://10.0.0.3",
             "enabled": True, "machine_type": "cnc_router"},
            # Non-CNC device must be ignored entirely.
            {"id": "fdm1", "name": "Printer One", "base_url": "http://10.0.0.4",
             "enabled": True, "machine_type": "fdm"},
            # Disabled CNC device must be ignored.
            {"id": "mill_off", "name": "Mill Off", "base_url": "http://10.0.0.5",
             "enabled": False, "machine_type": "cnc_mill"},
        ]
    }
    p = tmp_path / "devices.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setenv("MEMAR_CONFIG_PATH", str(p))
    cfgmod.reload_config_cache()
    yield p
    cfgmod.reload_config_cache()


async def _seed(device_id, samples):
    """Insert CNCMetricsLog rows. `samples` = list of (minutes_ago, psi)."""
    from app.db import AsyncSessionLocal
    from app.models_db import CNCMetricsLog

    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        for minutes_ago, psi in samples:
            db.add(CNCMetricsLog(
                device_id=device_id,
                timestamp=now - timedelta(minutes=minutes_ago),
                coolant_psi=psi,
                coolant_active=(psi is not None),
                machine_state="running",
            ))
        await db.commit()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Hard-fail any real httpx POST so a leaked network call is caught."""
    async def _boom(*a, **k):
        raise AssertionError("unexpected outbound httpx.AsyncClient.post")
    monkeypatch.setattr("httpx.AsyncClient.post", _boom)


@pytest_asyncio.fixture
async def clean_cnc_metrics(client):
    """Purge CNCMetricsLog before each test.

    The in-memory SQLite engine is module-level and shared, so create_all does
    NOT reset rows between tests — seeded rows leak across tests in a run. Delete
    them up front so each test sees only what it seeds, regardless of order.
    """
    from sqlalchemy import delete
    from app.db import AsyncSessionLocal
    from app.models_db import CNCMetricsLog

    async with AsyncSessionLocal() as db:
        await db.execute(delete(CNCMetricsLog))
        await db.commit()
    yield


@pytest.mark.asyncio
async def test_low_sustained_pressure_raises_alert(client, cnc_config, clean_cnc_metrics, monkeypatch):
    """All samples < 20 PSI spanning >= 5 min -> one alert for that device."""
    from app import coolant_alerts_integration as cai
    from app.messaging import get_hub

    monkeypatch.delenv("MEMAR_COOLANT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MEMAR_SLACK_WEBHOOK_URL", raising=False)

    sent = []
    async def _fake_broadcast(event):
        sent.append(event)
    monkeypatch.setattr(get_hub(), "broadcast", _fake_broadcast)

    # 8, 6, 4, 2, 0 min ago all below threshold -> span 8 min >= 5.
    await _seed("mill1", [(8, 12.0), (6, 11.0), (4, 10.5), (2, 9.0), (0, 8.0)])

    alerts = await cai.evaluate_coolant_alerts_once()

    assert len(alerts) == 1
    a = alerts[0]
    assert a["device_id"] == "mill1"
    assert a["device_name"] == "Mill One"   # name from config, not the row
    assert a["current_psi"] == 8.0          # newest sample
    assert a["threshold_psi"] == 20
    assert a["duration_minutes"] >= 5
    # Notification was dispatched through the messaging hub.
    assert len(sent) == 1
    assert sent[0].type == "cnc.coolant_low"


@pytest.mark.asyncio
async def test_healthy_pressure_no_alert(client, cnc_config, clean_cnc_metrics, monkeypatch):
    """Samples >= 20 PSI -> no breach."""
    from app import coolant_alerts_integration as cai
    monkeypatch.delenv("MEMAR_SLACK_WEBHOOK_URL", raising=False)

    await _seed("lathe1", [(8, 45.0), (4, 50.0), (0, 48.0)])

    alerts = await cai.evaluate_coolant_alerts_once()
    assert alerts == []


@pytest.mark.asyncio
async def test_low_but_not_sustained_no_alert(client, cnc_config, clean_cnc_metrics, monkeypatch):
    """Low PSI but spanning < 5 min -> not yet a sustained breach."""
    from app import coolant_alerts_integration as cai
    monkeypatch.delenv("MEMAR_SLACK_WEBHOOK_URL", raising=False)

    # Two low samples only 2 min apart -> span 2 min < 5.
    await _seed("router1", [(2, 10.0), (0, 9.0)])

    alerts = await cai.evaluate_coolant_alerts_once()
    assert alerts == []


@pytest.mark.asyncio
async def test_no_psi_data_skips_device_no_crash(client, cnc_config, clean_cnc_metrics, monkeypatch):
    """The common case today: coolant_psi is NULL. Device is skipped, no crash."""
    from app import coolant_alerts_integration as cai
    monkeypatch.delenv("MEMAR_SLACK_WEBHOOK_URL", raising=False)

    # Rows exist but every coolant_psi is None (NULL) — filtered out by query.
    await _seed("mill1", [(8, None), (4, None), (0, None)])
    # Other CNC devices have no rows at all.

    alerts = await cai.evaluate_coolant_alerts_once()
    assert alerts == []  # no data => no alert, no exception


@pytest.mark.asyncio
async def test_mixed_low_and_high_no_alert(client, cnc_config, clean_cnc_metrics, monkeypatch):
    """If any sample in the window is >= threshold, condition is not sustained."""
    from app import coolant_alerts_integration as cai
    monkeypatch.delenv("MEMAR_SLACK_WEBHOOK_URL", raising=False)

    await _seed("mill1", [(8, 9.0), (4, 30.0), (0, 8.0)])  # one healthy reading

    alerts = await cai.evaluate_coolant_alerts_once()
    assert alerts == []


@pytest.mark.asyncio
async def test_no_devices_no_alert(client, clean_cnc_metrics, monkeypatch):
    """With no CNC devices configured at all, evaluation is a clean no-op."""
    import app.config as cfgmod
    from app import coolant_alerts_integration as cai

    # Empty config (no printers).
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.write(fd, yaml.safe_dump({"printers": []}).encode())
    os.close(fd)
    monkeypatch.setenv("MEMAR_CONFIG_PATH", path)
    cfgmod.reload_config_cache()
    try:
        alerts = await cai.evaluate_coolant_alerts_once()
        assert alerts == []
    finally:
        cfgmod.reload_config_cache()
        os.unlink(path)


@pytest.mark.asyncio
async def test_slack_send_noop_when_url_unset(monkeypatch):
    """SlackIntegration.send_alert returns False and never touches the network
    when MEMAR_SLACK_WEBHOOK_URL is unset."""
    from app.slack_webhooks import SlackIntegration

    monkeypatch.delenv("MEMAR_SLACK_WEBHOOK_URL", raising=False)

    result = await SlackIntegration.send_alert(
        title="Test", message="hello", severity="critical",
    )
    assert result is False  # graceful no-op (httpx.post mock would raise if called)


@pytest.mark.asyncio
async def test_slack_send_posts_when_url_set(monkeypatch):
    """When the URL is set, send_alert POSTs once and returns True on 200."""
    from app.slack_webhooks import SlackIntegration

    monkeypatch.setenv("MEMAR_SLACK_WEBHOOK_URL", "https://hooks.example/test")

    class _Resp:
        status_code = 200

    posted = {}
    async def _ok_post(self, url, json=None, **kwargs):
        posted["url"] = url
        posted["json"] = json
        return _Resp()
    monkeypatch.setattr("httpx.AsyncClient.post", _ok_post)

    result = await SlackIntegration.send_alert(
        title="Coolant", message="critical", severity="critical",
        device_name="Mill One",
    )
    assert result is True
    assert posted["url"] == "https://hooks.example/test"
    assert "attachments" in posted["json"]


@pytest.mark.asyncio
async def test_depletion_rate_positive_when_psi_dropping(client, clean_cnc_metrics):
    """HIGH-COOLANT-SIGN-01 regression: a machine whose coolant PSI FALLS over
    24h must yield a POSITIVE depletion rate and a 'declining' status. On the
    pre-fix inverted sign the rate is negative, so it reports 'healthy' and
    never predicts the real depletion.

    device_name is passed explicitly so the predictor skips the config lookup.
    Seed a >24h-old high-PSI sample and a current low-PSI sample (still >= the
    20-PSI critical line so the status is 'declining', not 'critical')."""
    from app.db import AsyncSessionLocal
    from app.models_db import CNCMetricsLog
    from app.coolant_models import CoolantDepletionPredictor

    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        db.add(CNCMetricsLog(
            device_id="mill_depl", timestamp=now - timedelta(hours=25),
            coolant_psi=100.0, coolant_active=True, machine_state="running",
        ))
        db.add(CNCMetricsLog(
            device_id="mill_depl", timestamp=now,
            coolant_psi=30.0, coolant_active=True, machine_state="running",
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        predictor = CoolantDepletionPredictor(db)
        analysis = await predictor.analyze_device("mill_depl", device_name="Depleting Mill")

    assert analysis.depletion_rate_psi_per_hour is not None
    assert analysis.depletion_rate_psi_per_hour > 0, (
        f"expected positive depletion rate for falling PSI, got "
        f"{analysis.depletion_rate_psi_per_hour}"
    )
    assert analysis.status == "declining", f"got status={analysis.status}"
    assert analysis.alert_triggered is True
