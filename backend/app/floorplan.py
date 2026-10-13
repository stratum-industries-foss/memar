"""Floor plan image upload and device layout CRUD."""
import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess  # noqa: F401  (kept for parity with claude-shim subprocess pattern)
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_config
from .db import get_db
from .deps import get_current_user, require_feature, require_role
from .models_db import FloorPlan3DCache, FloorPlanLayout
from .ssrf import assert_safe_http_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/floorplan", tags=["floorplan"])
DATA_DIR = Path(os.getenv("MEMAR_DATA_DIR", "./data"))

# --- Higgsfield 3D floor-plan render config ---------------------------------
# Optional feature: renders an AI 3D overlay on top of the (always-available)
# 2D floor plan. Explicit HIGGSFIELD_CLI env var wins if set (matches
# claude-shim's absolute-path pattern, for a systemd unit whose PATH may not
# include it); otherwise a real PATH lookup, so any install that has the CLI
# on PATH picks it up automatically. No hardcoded personal-machine fallback —
# there's no path that's correct for any install but one specific developer's
# own machine, and the 3D render already fails clean (502) with none set.
HIGGSFIELD_CLI = os.getenv("HIGGSFIELD_CLI") or shutil.which("higgsfield") or ""
HIGGSFIELD_HOME = os.getenv("HIGGSFIELD_HOME", os.path.expanduser("~"))
FLOORPLAN_3D_DIR = DATA_DIR / "floorplan_3d"
# Bump to invalidate every cached render at once (prompt/style change).
PROMPT_VERSION = 1
# Guardrail: at most this many fresh renders may be kicked off per rolling 24h.
GEN_3D_QUOTA_24H = 10
HF_CREATE_TIMEOUT = 30.0   # seconds — job creation
HF_POLL_TIMEOUT = 300.0    # seconds — status poll (5m)

# machine_type -> human label used in the render prompt.
_MACHINE_LABELS = {
    "fdm": "FDM 3D printer",
    "sla": "SLA resin 3D printer",
    "idex": "IDEX dual-extruder 3D printer",
    "cnc_mill": "CNC milling machine",
    "cnc_lathe": "CNC lathe",
    "cnc_router": "CNC router",
    "laser": "laser cutter",
    "plasma": "plasma cutter",
    "waterjet": "waterjet cutter",
    "vinyl": "vinyl cutter",
    "pick_and_place": "pick-and-place machine",
    "embroidery": "embroidery machine",
    "wire_edm": "wire EDM machine",
}

_PROMPT_TEMPLATE = (
    "Isometric 3D technical floor plan of a compact manufacturing workshop. "
    "{device_count} pieces of equipment arranged on a clean grid floor: "
    "{device_types}. Schematic CAD-style rendering, muted white-and-gray "
    "palette with subtle blue accents, soft ambient occlusion, orthographic "
    "isometric projection (30-degree), no text labels, no people, no clutter, "
    "professional engineering diagram aesthetic, top-down-angled view."
)


class Generate3DRequest(BaseModel):
    # Optional override — normally the fleet is read from config. Empty body is
    # the common case (POST with no JSON), so every field is optional.
    fleet_id: str | None = Field(default=None, max_length=255)


class DevicePosition(BaseModel):
    device_id: str = Field(max_length=255)
    x: int = Field(default=0, ge=-100_000, le=100_000)
    y: int = Field(default=0, ge=-100_000, le=100_000)
    rotation: int = Field(default=0, ge=-360, le=360)


class LayoutUpdateRequest(BaseModel):
    devices: list[DevicePosition] = Field(max_length=500)


@router.post("/image")
async def upload_floorplan_image(
    file: UploadFile = File(...),
    _: dict = Depends(get_current_user),
    __: dict = Depends(require_role("admin", "operator")),
    ___: None = Depends(require_feature("floor_plan")),
) -> dict:
    """
    Upload a floor plan image.
    Requires admin or operator role.
    """
    # Validate content type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image (content-type must start with 'image/')",
        )

    # Create data directory if it doesn't exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Read file content (capped at 20MB)
    buf = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image too large (max 20MB)")
    content = bytes(buf)

    # Sniff magic bytes — content-type header is client-controlled
    if not content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF", b"GIF8")):
        raise HTTPException(status_code=400, detail="File is not a recognized image (PNG/JPEG/WebP/GIF)")

    # Write to disk
    image_path = DATA_DIR / "floorplan.png"
    with open(image_path, "wb") as f:
        f.write(content)

    return {
        "message": "Floor plan image uploaded successfully",
        "path": str(image_path),
        "size": len(content),
    }


@router.get("/image")
async def get_floorplan_image(
    _: dict = Depends(get_current_user),
    __: None = Depends(require_feature("floor_plan")),
) -> Response:
    """
    Download the floor plan image.
    """
    image_path = DATA_DIR / "floorplan.png"

    if not image_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Floor plan image not found",
        )

    with open(image_path, "rb") as f:
        content = f.read()

    return Response(content=content, media_type="image/png")


@router.get("/layout")
async def get_floorplan_layout(
    _: dict = Depends(get_current_user),
    __: None = Depends(require_feature("floor_plan")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get the current floor plan layout (device positions).
    Returns image_set flag and list of device positions.
    """
    # Check if image exists
    image_path = DATA_DIR / "floorplan.png"
    image_set = image_path.exists()

    # Query all device positions from database
    result = await db.execute(select(FloorPlanLayout))
    layouts = result.scalars().all()

    # Filter devices to only those in current config (T126)
    config = get_config()
    live_ids = {p.id for p in config.printers}

    devices = [
        {
            "device_id": layout.device_id,
            "x": layout.x,
            "y": layout.y,
            "rotation": layout.rotation,
        }
        for layout in layouts
        if layout.device_id in live_ids
    ]

    return {
        "image_set": image_set,
        "devices": devices,
        "higgsfield_available": bool(HIGGSFIELD_CLI),
    }


@router.put("/layout")
async def update_floorplan_layout(
    request: LayoutUpdateRequest,
    _: dict = Depends(get_current_user),
    __: dict = Depends(require_role("admin", "operator")),
    ___: None = Depends(require_feature("floor_plan")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Update device positions in the floor plan layout.
    Uses INSERT OR REPLACE (merge) to upsert each device.
    Requires admin or operator role (matches image upload / device delete).
    """
    updated_count = 0

    for device_pos in request.devices:
        # Merge: find existing or create new
        result = await db.execute(
            select(FloorPlanLayout).where(FloorPlanLayout.device_id == device_pos.device_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            existing.x = device_pos.x
            existing.y = device_pos.y
            existing.rotation = device_pos.rotation
            db.add(existing)
        else:
            # Create new
            new_layout = FloorPlanLayout(
                device_id=device_pos.device_id,
                x=device_pos.x,
                y=device_pos.y,
                rotation=device_pos.rotation,
            )
            db.add(new_layout)

        updated_count += 1

    await db.commit()

    return {
        "message": "Floor plan layout updated",
        "devices_updated": updated_count,
    }


@router.delete("/layout/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floorplan_device(
    device_id: str,
    _: dict = Depends(get_current_user),
    __: dict = Depends(require_role("admin", "operator")),
    ___: None = Depends(require_feature("floor_plan")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Remove a device's floor plan position.
    Idempotent: returns 204 whether or not the device had a saved position
    (e.g. cleanup after removing a device from the fleet config).
    """
    result = await db.execute(
        select(FloorPlanLayout).where(FloorPlanLayout.device_id == device_id)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        await db.delete(existing)
        await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 3D floor-plan render (Higgsfield) --------------------------------------


def _fleet_devices() -> tuple[list[str], list[str]]:
    """Return (machine_type_values, human_labels) for enabled fleet devices.

    Positions in floor_plan_layouts don't change WHICH machines exist — only
    where they sit — so the render signature is driven by the config fleet
    (device count + machine types), which is what the picture actually depicts.
    """
    cfg = get_config()
    types: list[str] = []
    labels: list[str] = []
    for p in cfg.printers:
        if not getattr(p, "enabled", True):
            continue
        mt = getattr(p.machine_type, "value", str(p.machine_type))
        types.append(mt)
        labels.append(_MACHINE_LABELS.get(mt, mt.replace("_", " ")))
    return types, labels


def _compute_signature(device_types: list[str], prompt_version: int) -> str:
    payload = f"{len(device_types)}|{'|'.join(sorted(device_types))}|v{prompt_version}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _build_prompt(device_count: int, labels: list[str]) -> str:
    # Collapse duplicate labels into "3x FDM 3D printer" style phrases so the
    # prompt stays compact for large fleets and the model gets accurate counts.
    from collections import Counter

    counts = Counter(labels)
    parts = [f"{n}x {lbl}" if n > 1 else lbl for lbl, n in counts.items()]
    device_types = ", ".join(parts) if parts else "assorted CNC and 3D-printing equipment"
    return _PROMPT_TEMPLATE.format(device_count=device_count, device_types=device_types)


async def _run_higgsfield(args: list[str], timeout: float) -> str:
    """Run the higgsfield CLI, NixOS-hardened (absolute path, no shell, explicit
    HOME, inherited PATH, stdin closed). Returns stdout text.

    Raises HTTPException(502/504) on failure or timeout.
    """
    env = {**os.environ, "HOME": HIGGSFIELD_HOME}
    try:
        proc = await asyncio.create_subprocess_exec(
            HIGGSFIELD_CLI,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
        )
    except (FileNotFoundError, PermissionError):
        # An empty/unconfigured HIGGSFIELD_CLI resolves to "" (see module-level
        # default above), and execve("") raises PermissionError on Linux rather
        # than FileNotFoundError -- catch both so "not configured" degrades to
        # 502 instead of an unhandled 500.
        raise HTTPException(status_code=502, detail="Higgsfield CLI not found on server")
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise HTTPException(status_code=504, detail="Higgsfield request timed out")
    if proc.returncode != 0:
        msg = (err.decode(errors="replace").strip() or "unknown error")[:300]
        logger.warning("higgsfield %s failed rc=%s: %s", args[:2], proc.returncode, msg)
        raise HTTPException(status_code=502, detail=f"Higgsfield error: {msg}")
    return out.decode(errors="replace")


def _download_to(url: str, dest: Path) -> None:
    # SSRF protection: validate URL before opening
    assert_safe_http_url(url)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("External URLs must use HTTPS")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (SSRF-validated above)
        data = r.read()
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def _ready_payload(row: FloorPlan3DCache) -> dict:
    return {
        "status": "ready",
        "job_id": row.id,
        "image_url": f"/api/floorplan/image/3d/{row.id}/render",
    }


@router.post("/image/3d")
async def generate_floorplan_3d(
    request: Generate3DRequest | None = None,
    _: dict = Depends(get_current_user),
    __: dict = Depends(require_role("admin", "operator")),
    ___: None = Depends(require_feature("floor_plan")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Request (or re-serve) an AI-generated isometric 3D render of the fleet floor
    plan. Cached by fleet signature: an unchanged fleet re-serves the existing
    image (200) instead of re-billing Higgsfield. A cache miss kicks off a new
    Higgsfield job and returns 202 (poll GET /image/3d/{job_id} for readiness).
    """
    fleet_id = request.fleet_id if request else None
    types, labels = _fleet_devices()
    device_count = len(types)
    signature = _compute_signature(types, PROMPT_VERSION)

    # Cache lookup.
    existing = (
        await db.execute(
            select(FloorPlan3DCache).where(FloorPlan3DCache.signature == signature)
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status == "ready" and existing.image_path and Path(existing.image_path).exists():
            return Response(
                content=json.dumps(_ready_payload(existing)),
                media_type="application/json",
                status_code=status.HTTP_200_OK,
            )
        if existing.status == "pending":
            # Job already in flight for this exact fleet — dedupe, don't re-bill.
            return Response(
                content=json.dumps({"status": "pending", "job_id": existing.id}),
                media_type="application/json",
                status_code=status.HTTP_202_ACCEPTED,
            )
        # status == "failed" (or ready-but-file-missing) -> regenerate below,
        # reusing this row so the unique signature constraint isn't violated.

    # Quota guardrail (rolling 24h) — only gates NEW jobs, not cache re-serves.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = (
        await db.execute(
            select(func.count())
            .select_from(FloorPlan3DCache)
            .where(FloorPlan3DCache.created_at >= cutoff)
        )
    ).scalar_one()
    if recent >= GEN_3D_QUOTA_24H:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"3D render quota reached ({GEN_3D_QUOTA_24H}/24h). Try again later.",
        )

    prompt = _build_prompt(device_count, labels)
    out = await _run_higgsfield(
        [
            "generate", "create", "gpt_image_2",
            "--prompt", prompt,
            "--aspect_ratio", "16:9",
            "--resolution", "2k",
            "--json",
        ],
        timeout=HF_CREATE_TIMEOUT,
    )
    try:
        parsed = json.loads(out)
        # create --json returns a JSON array of job ids: ["<uuid>"]
        hf_job_id = parsed[0] if isinstance(parsed, list) else parsed.get("id")
        if not hf_job_id:
            raise ValueError("no job id in response")
    except (json.JSONDecodeError, ValueError, IndexError, KeyError, TypeError) as e:
        logger.warning("higgsfield create: unparseable output: %s", out[:300])
        raise HTTPException(status_code=502, detail=f"Higgsfield returned no job id ({e})")

    if existing is not None:
        # Reuse the row for a failed/stale signature.
        existing.hf_job_id = hf_job_id
        existing.status = "pending"
        existing.image_path = None
        existing.error = None
        existing.prompt = prompt
        existing.prompt_version = PROMPT_VERSION
        existing.fleet_id = fleet_id
        existing.generated_at = None
        existing.created_at = datetime.now(timezone.utc)
        db.add(existing)
        await db.commit()
        row_id = existing.id
    else:
        row = FloorPlan3DCache(
            fleet_id=fleet_id,
            signature=signature,
            hf_job_id=hf_job_id,
            status="pending",
            prompt=prompt,
            prompt_version=PROMPT_VERSION,
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent POST already inserted this signature — return theirs.
            await db.rollback()
            dupe = (
                await db.execute(
                    select(FloorPlan3DCache).where(FloorPlan3DCache.signature == signature)
                )
            ).scalar_one()
            return Response(
                content=json.dumps({"status": dupe.status, "job_id": dupe.id}),
                media_type="application/json",
                status_code=status.HTTP_202_ACCEPTED,
            )
        row_id = row.id

    return Response(
        content=json.dumps({"status": "pending", "job_id": row_id}),
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get("/image/3d/{job_id}")
async def poll_floorplan_3d(
    job_id: int,
    _: dict = Depends(get_current_user),
    __: None = Depends(require_feature("floor_plan")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Poll the status of a 3D render job. Drives the pending->ready|failed
    transition: on a pending row it queries Higgsfield, and on completion
    downloads the PNG to disk and flips the row to ready.
    """
    row = await db.get(FloorPlan3DCache, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Render job not found")

    if row.status == "ready" and row.image_path and Path(row.image_path).exists():
        return _ready_payload(row)
    if row.status == "failed":
        return {"status": "failed", "job_id": row.id, "error": row.error}
    if not row.hf_job_id:
        return {"status": "pending", "job_id": row.id}

    # status == pending (or ready-but-file-missing): ask Higgsfield.
    out = await _run_higgsfield(
        ["generate", "get", row.hf_job_id, "--json"],
        timeout=HF_POLL_TIMEOUT,
    )
    try:
        job = json.loads(out)
    except json.JSONDecodeError:
        logger.warning("higgsfield get: unparseable output: %s", out[:300])
        return {"status": "pending", "job_id": row.id}

    hf_status = job.get("status")
    if hf_status == "completed":
        # A genuinely completed job always carries result_url (a full-res PNG).
        # Don't fall back to min_result_url — that's a .webp and we serve
        # image/png; a null result_url means not-actually-ready-yet.
        result_url = job.get("result_url")
        if not result_url:
            return {"status": "pending", "job_id": row.id}
        dest = FLOORPLAN_3D_DIR / f"{row.id}.png"
        try:
            await asyncio.to_thread(_download_to, result_url, dest)
        except Exception as e:  # noqa: BLE001 — surface download failure as job failure
            row.status = "failed"
            row.error = f"download failed: {e}"[:500]
            db.add(row)
            await db.commit()
            return {"status": "failed", "job_id": row.id, "error": row.error}
        row.status = "ready"
        row.image_path = str(dest.resolve())
        row.generated_at = datetime.now(timezone.utc)
        row.error = None
        db.add(row)
        await db.commit()
        return _ready_payload(row)

    if hf_status in ("failed", "nsfw", "canceled", "cancelled", "error"):
        row.status = "failed"
        row.error = job.get("fail_reason") or f"Higgsfield status: {hf_status}"
        db.add(row)
        await db.commit()
        return {"status": "failed", "job_id": row.id, "error": row.error}

    # queued / in_progress / anything else -> still working.
    return {"status": "pending", "job_id": row.id}


@router.get("/image/3d/{job_id}/render")
async def render_floorplan_3d(
    job_id: int,
    _: dict = Depends(get_current_user),
    __: None = Depends(require_feature("floor_plan")),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Serve the generated 3D render PNG for a ready job."""
    row = await db.get(FloorPlan3DCache, job_id)
    if row is None or row.status != "ready" or not row.image_path:
        raise HTTPException(status_code=404, detail="3D render not available")
    path = Path(row.image_path)
    # Path confinement: ensure file is within the floorplan 3D assets directory
    if not path.resolve().is_relative_to(FLOORPLAN_3D_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not path.exists():
        raise HTTPException(status_code=404, detail="3D render file missing")
    return FileResponse(str(path), media_type="image/png", filename=f"floorplan_3d_{row.id}.png")
