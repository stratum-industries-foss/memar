"""Packaging checks that the source tree alone cannot show.

- Every module the image copies must be readable by the runtime user (uid 10001).
  A 0600 file made by a private edit imports fine as the developer and then fails
  inside the container (task 84 found this).
- Runtime state (signing keys, databases) must never be in the build context.
"""

import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _ignored_patterns() -> list[str]:
    dockerignore = ROOT / ".dockerignore"
    if not dockerignore.exists():  # the hermetic test sandbox copies only backend/
        pytest.skip("no .dockerignore in this build context")
    lines = dockerignore.read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def test_dockerignore_excludes_runtime_state_at_any_depth():
    pats = _ignored_patterns()
    assert "data/" in pats
    assert "**/data/" in pats, "a nested backend/data/ (signing key) must not reach the image"
    assert "**/jwt-secret" in pats


@pytest.mark.parametrize("subdir", ["backend/app", "backend/tests"])
def test_python_sources_are_world_readable(subdir):
    unreadable = []
    for path in (ROOT / subdir).rglob("*.py"):
        mode = stat.S_IMODE(path.stat().st_mode)
        if not mode & stat.S_IROTH:
            unreadable.append(str(path.relative_to(ROOT)))
    assert not unreadable, f"not readable by the runtime user: {unreadable}"


def test_no_signing_key_file_in_the_source_tree_build_context():
    # The key lives in the data directory, which is git-ignored and docker-ignored.
    tracked_key = ROOT / "backend" / "data" / "jwt-secret"
    if tracked_key.exists():
        assert "**/data/" in _ignored_patterns()
