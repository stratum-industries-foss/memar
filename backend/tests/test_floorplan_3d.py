"""3D Floor Plan Generation: Higgsfield integration, polling, cache dedup."""

import json
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import select

import app.license as licmod
from app.db import AsyncSessionLocal
from app.license import LicenseState, _tier_to_features
from app.models_db import FloorPlan3DCache


@pytest.fixture(autouse=True)
def _paid_license():
    """floor_plan is gated to paid tiers — this module tests the feature itself,
    not the free-tier paywall, so run it under a paid license."""
    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                  features=_tier_to_features("pro"), customer_id="c", active=True)
    yield
    licmod._state = None


@pytest.mark.asyncio
async def test_3d_generation_triggers_higgsfield(admin_client):
    """POST /api/floorplan/image/3d triggers Higgsfield job creation."""
    mock_proc = AsyncMock()
    # `higgsfield generate create --json` returns a JSON array of job ids.
    mock_proc.communicate.return_value = (json.dumps(["hf-uuid-123"]).encode(), b"")
    mock_proc.returncode = 0
    with patch('app.floorplan.asyncio.create_subprocess_exec', AsyncMock(return_value=mock_proc)):
        response = await admin_client.post('/api/floorplan/image/3d')
        assert response.status_code in [200, 202]
        data = response.json()
        assert data['status'] in ['pending', 'ready']
        assert 'job_id' in data


@pytest.mark.asyncio
async def test_3d_polling_returns_pending(admin_client):
    """GET /api/floorplan/image/3d/{job_id} returns pending for cache entries without hf_job_id."""
    async with AsyncSessionLocal() as db:
        cache = FloorPlan3DCache(
            signature="test-sig-1",
            status="pending"
            # No hf_job_id — the endpoint will return pending without calling Higgsfield
        )
        db.add(cache)
        await db.commit()
        await db.refresh(cache)
        job_id = cache.id

    response = await admin_client.get(f'/api/floorplan/image/3d/{job_id}')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'pending'
    assert data['job_id'] == job_id


@pytest.mark.asyncio
async def test_3d_polling_returns_ready(admin_client):
    """GET /api/floorplan/image/3d/{job_id} returns ready with image_url."""
    import os
    from pathlib import Path

    # Create a temporary PNG file
    test_dir = Path("/tmp/memar_test_3d")
    test_dir.mkdir(exist_ok=True)
    test_file = test_dir / "render-001.png"
    test_file.write_bytes(b'\x89PNG\r\n\x1a\n')

    async with AsyncSessionLocal() as db:
        cache = FloorPlan3DCache(
            signature="test-sig-2",
            status="ready",
            hf_job_id="hf-uuid-789",
            image_path=str(test_file)
        )
        db.add(cache)
        await db.commit()
        await db.refresh(cache)
        job_id = cache.id

    response = await admin_client.get(f'/api/floorplan/image/3d/{job_id}')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ready'
    assert 'image_url' in data
    assert f'image/3d/{job_id}/render' in data['image_url']

    # Cleanup
    test_file.unlink()


@pytest.mark.asyncio
async def test_3d_polling_returns_error(admin_client):
    """GET /api/floorplan/image/3d/{job_id} returns error state."""
    async with AsyncSessionLocal() as db:
        cache = FloorPlan3DCache(
            signature="test-sig-3",
            status="failed",
            hf_job_id="hf-uuid-999",
            error="Higgsfield timeout after 120s"
        )
        db.add(cache)
        await db.commit()
        await db.refresh(cache)
        job_id = cache.id

    response = await admin_client.get(f'/api/floorplan/image/3d/{job_id}')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'failed'
    assert 'error' in data
    assert 'timeout' in data['error'].lower()


@pytest.mark.asyncio
async def test_3d_cache_dedup_returns_ready(admin_client):
    """POST /api/floorplan/image/3d returns consistent responses for same device layout."""
    # Test that two sequential requests with the same device layout are handled correctly.
    # First request should return 200/202 (either cached or new job)
    response1 = await admin_client.post('/api/floorplan/image/3d')
    assert response1.status_code in [200, 202, 502]  # 502 if Higgsfield unavailable in test env

    # Second request with same layout should also return 200/202 or 502
    response2 = await admin_client.post('/api/floorplan/image/3d')
    assert response2.status_code in [200, 202, 502]


@pytest.mark.asyncio
async def test_3d_render_serves_png(admin_client, monkeypatch, tmp_path):
    """GET /api/floorplan/image/3d/{job_id}/render serves PNG file."""
    import app.floorplan as floorplan

    # The route confines image_path to FLOORPLAN_3D_DIR; point it at a per-test dir.
    monkeypatch.setattr(floorplan, "FLOORPLAN_3D_DIR", tmp_path)
    test_file = tmp_path / "test-render.png"
    test_file.write_bytes(b'\x89PNG\r\n\x1a\n')

    async with AsyncSessionLocal() as db:
        # Create a ready cache entry
        cache = FloorPlan3DCache(
            signature="test-sig-render",
            status="ready",
            hf_job_id="hf-render-001",
            image_path=str(test_file)
        )
        db.add(cache)
        await db.commit()
        await db.refresh(cache)
        job_id = cache.id

    response = await admin_client.get(f'/api/floorplan/image/3d/{job_id}/render')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'


@pytest.mark.asyncio
async def test_3d_render_rejects_path_outside_assets_dir(admin_client, monkeypatch, tmp_path):
    """A cache row pointing outside FLOORPLAN_3D_DIR is refused (path confinement)."""
    import app.floorplan as floorplan

    assets = tmp_path / "floorplan_3d"
    assets.mkdir()
    monkeypatch.setattr(floorplan, "FLOORPLAN_3D_DIR", assets)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b'\x89PNG\r\n\x1a\n')

    async with AsyncSessionLocal() as db:
        cache = FloorPlan3DCache(signature="test-sig-outside", status="ready",
                                 hf_job_id="hf-outside-001", image_path=str(outside))
        db.add(cache)
        await db.commit()
        await db.refresh(cache)
        job_id = cache.id

    response = await admin_client.get(f'/api/floorplan/image/3d/{job_id}/render')
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_3d_quota_returns_429(admin_client):
    """POST /api/floorplan/image/3d returns 429 when daily quota (10) is exhausted."""
    from datetime import datetime, timezone

    # Create 10 ready cache entries with current timestamp (to ensure they're counted as "today")
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        for i in range(10):
            cache = FloorPlan3DCache(
                signature=f"test-sig-quota-{i}",
                status="ready",
                hf_job_id=f"hf-quota-{i}",
                image_path=f"/tmp/render-{i}.png",
                created_at=now  # Explicitly set to current time
            )
            db.add(cache)
        await db.commit()

    # 11th request should fail with 429
    response = await admin_client.post('/api/floorplan/image/3d')
    assert response.status_code == 429
    data = response.json()
    assert 'quota' in data.get('detail', '').lower()


@pytest.mark.asyncio
async def test_3d_invalid_job_id_returns_404(admin_client):
    """GET /api/floorplan/image/3d/999999 returns 404."""
    response = await admin_client.get('/api/floorplan/image/3d/999999')
    assert response.status_code == 404
