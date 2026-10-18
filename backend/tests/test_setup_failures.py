"""Failed setup-code attempts are counted per client and globally; successes are not."""

import pytest

from app import setup_failures as sf


@pytest.fixture(autouse=True)
def _fresh():
    sf.reset()
    yield
    sf.reset()


def test_only_failures_count():
    for _ in range(sf.PER_CLIENT_MAX):
        assert sf.check("203.0.113.9", now=0) == 0  # no failures yet: allowed
    # Successful requests were never recorded, so the client is still allowed.
    assert sf.check("203.0.113.9", now=1) == 0


def test_guessing_client_is_blocked_then_recovers():
    for i in range(sf.PER_CLIENT_MAX):
        sf.record_failure("203.0.113.9", now=i)
    wait = sf.check("203.0.113.9", now=10)
    assert 0 < wait <= sf.PER_CLIENT_WINDOW_S
    # After the window passes, the owner can try again.
    assert sf.check("203.0.113.9", now=10 + sf.PER_CLIENT_WINDOW_S + 5) == 0


def test_owner_is_not_locked_out_by_a_different_clients_failures():
    for i in range(sf.PER_CLIENT_MAX):
        sf.record_failure("203.0.113.9", now=i)
    # Another address is not blocked by the attacker's per-client count.
    assert sf.check("192.168.1.20", now=10) == 0


def test_owner_can_mistype_a_few_times_without_lockout():
    for i in range(sf.PER_CLIENT_MAX - 1):
        sf.record_failure("192.168.1.20", now=i)
    assert sf.check("192.168.1.20", now=10) == 0


def test_global_cap_stops_distributed_guessing():
    for n in range(sf.GLOBAL_MAX):
        sf.record_failure(f"198.51.100.{n % 250}", now=n)
    assert sf.check("192.168.1.99", now=100) > 0
