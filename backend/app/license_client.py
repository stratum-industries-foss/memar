"""Client for the remote license heartbeat (subscription status check).

POSTs the current license key to the worker's /license/status endpoint. The
worker verifies the key, checks the live Stripe subscription, and — when active —
returns a freshly-signed key with a later expiry so the device's entitlement
auto-extends without any manual key paste. Network/HTTP failures return None,
which the caller treats as "hold current state" (the key lapses on its own
embedded expiry — the grace window).
"""
import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_license_status(url: str, current_key: str, timeout: float = 10.0) -> dict | None:
    """POST the current key to the heartbeat URL; return the JSON dict, or None on
    any network/HTTP failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={"key": current_key})
        if resp.status_code != 200:
            logger.debug("license heartbeat returned HTTP %s", resp.status_code)
            return None
        return resp.json()
    except Exception as e:  # noqa: BLE001 — any failure = hold current state
        logger.debug("license heartbeat request failed: %s", e)
        return None
