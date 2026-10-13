"""BACKEND-CORE-BLOCKING-01: _notify_owner_enterprise called smtplib directly
inside an async function — fully synchronous SMTP I/O (DNS + TCP + TLS +
send) blocked the whole event loop for its duration on every enterprise-tier
signup. asyncio.to_thread offloads it to a worker thread instead.

Same technique as test_billing_event_loop_blocking.py: this can't be an
output-equality test (the function returns None either way), so measure
whether two concurrent calls overlap (~1x a single call's duration) or run
back-to-back (~2x) on the shared event loop.
"""
import asyncio
import time

import pytest

from app.stripe_webhook import _notify_owner_enterprise

BLOCK_SECONDS = 0.3


class _FakeSMTP:
    def __init__(self, host, port):
        pass

    def __enter__(self):
        time.sleep(BLOCK_SECONDS)  # simulates SMTP round-trip; must run off the loop
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        pass


@pytest.mark.asyncio
async def test_notify_owner_enterprise_does_not_block_event_loop(monkeypatch):
    monkeypatch.setenv("MEMAR_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MEMAR_SMTP_USER", "bot@example.com")
    monkeypatch.setenv("MEMAR_SMTP_PASSWORD", "hunter2")

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    start = time.monotonic()
    await asyncio.gather(
        _notify_owner_enterprise("owner@x.com", "cust1@x.com", "scale", "cus_1"),
        _notify_owner_enterprise("owner@x.com", "cust2@x.com", "scale", "cus_2"),
    )
    elapsed = time.monotonic() - start

    # Pre-fix: each call's synchronous smtplib.SMTP block monopolizes the
    # event loop, so two concurrent calls run back-to-back (~2x BLOCK_SECONDS).
    # Post-fix: both run concurrently in worker threads (~1x).
    assert elapsed < BLOCK_SECONDS * 1.7, (
        f"two concurrent notifications took {elapsed:.2f}s (~{elapsed / BLOCK_SECONDS:.1f}x a "
        f"single call) — looks sequential/blocking, not concurrent"
    )
