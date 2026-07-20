import asyncio
import uuid
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.common import ApiResponse
from app.schemas.nvr import (
    NvrCreate,
    NvrUpdate,
    NvrResponse,
    CheckIpRequest,
    CheckIpResponse,
    NvrDiscoverRequest,
    NvrDiscoverResponse,
)
from app.models.nvr import Nvr
from app.models.camera import Camera, CameraStatus
from app.auth.permissions import require_manager_up, require_any
from app.services.go2rtc_config import sync_cameras
from app.services.nvr_discovery import NvrDiscoveryService

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["NVRs"])


async def _count_cameras(session: AsyncSession, nvr_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(Camera).where(Camera.nvr_id == nvr_id)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def _sync_after_change(session: AsyncSession) -> None:
    """Trigger go2rtc config sync after a camera-impacting change."""
    from app.services.camera_service import CameraService
    cam_service = CameraService(session)
    all_cams = await cam_service.list_all()
    cam_data = [
        {"id": str(c.id), "stream_url": c.stream_url}
        for c in all_cams
        if c.status.value in ("active", "online") and c.stream_url
    ]
    await sync_cameras(cam_data)


def _build_stream_url(nvr: Nvr, channel: int, prefer_rtsp: bool = True) -> str:
    """Build the stream URL for a camera channel on this NVR.

    If prefer_rtsp is True and the NVR has RTSP available, returns an
    RTSP URL. Otherwise returns dvrip:// URL.
    """
    cred = ""
    if nvr.username:
        cred = f"{nvr.username}:{nvr.password or ''}@"

    if prefer_rtsp:
        return (
            f"rtsp://{cred}{nvr.ip_address}:554"
            f"/user={nvr.username}&password={nvr.password or ''}"
            f"&channel={channel + 1}&stream=1.sdp?real_stream"
        )
    return f"dvrip://{cred}{nvr.ip_address}:{nvr.port}/{channel}"


@router.get("/nvrs", summary="List NVRs")
async def list_nvrs(
    warehouse_id: uuid.UUID | None = None,
    _any: None = Depends(require_any),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    stmt = select(Nvr)
    if warehouse_id:
        stmt = stmt.where(Nvr.warehouse_id == warehouse_id)
    stmt = stmt.order_by(Nvr.name)
    result = await session.execute(stmt)
    nvrs = list(result.scalars().all())

    data = []
    for nvr in nvrs:
        nvr_data = NvrResponse.model_validate(nvr).model_dump(mode="json")
        nvr_data["camera_count"] = await _count_cameras(session, nvr.id)
        data.append(nvr_data)

    return ApiResponse(success=True, data=data)


@router.post("/nvrs", status_code=201, summary="Create an NVR")
async def create_nvr(
    body: NvrCreate,
    _admin: None = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    nvr = Nvr(
        warehouse_id=body.warehouse_id,
        name=body.name,
        ip_address=body.ip_address,
        port=body.port,
        protocol=body.protocol,
        username=body.username,
        password=body.password,
        is_tailscale=body.is_tailscale,
    )
    session.add(nvr)
    await session.flush()

    LOGGER.info("NVR created: %s (%s @ %s)", nvr.id, nvr.name, nvr.ip_address)
    return ApiResponse(
        success=True,
        data=NvrResponse.model_validate(nvr).model_dump(mode="json"),
    )


@router.get("/nvrs/{nvr_id}", summary="Get an NVR")
async def get_nvr(
    nvr_id: uuid.UUID,
    _any: None = Depends(require_any),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    nvr = await session.get(Nvr, nvr_id)
    if not nvr:
        return ApiResponse(success=False, error={"code": "NOT_FOUND", "message": "NVR not found"})

    data = NvrResponse.model_validate(nvr).model_dump(mode="json")
    data["camera_count"] = await _count_cameras(session, nvr.id)
    return ApiResponse(success=True, data=data)


@router.put("/nvrs/{nvr_id}", summary="Update an NVR")
async def update_nvr(
    nvr_id: uuid.UUID,
    body: NvrUpdate,
    _admin: None = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    nvr = await session.get(Nvr, nvr_id)
    if not nvr:
        return ApiResponse(success=False, error={"code": "NOT_FOUND", "message": "NVR not found"})

    for field in body.model_fields_set:
        setattr(nvr, field, getattr(body, field))
    await session.flush()

    LOGGER.info("NVR updated: %s (fields: %s)", nvr_id, list(body.model_fields_set))
    return ApiResponse(
        success=True,
        data=NvrResponse.model_validate(nvr).model_dump(mode="json"),
    )


@router.delete("/nvrs/{nvr_id}", summary="Delete an NVR")
async def delete_nvr(
    nvr_id: uuid.UUID,
    _admin: None = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    nvr = await session.get(Nvr, nvr_id)
    if not nvr:
        return ApiResponse(success=False, error={"code": "NOT_FOUND", "message": "NVR not found"})

    # Unlink cameras from this NVR
    stmt = select(Camera).where(Camera.nvr_id == nvr_id)
    result = await session.execute(stmt)
    for cam in result.scalars().all():
        cam.nvr_id = None

    await session.delete(nvr)
    await session.flush()

    await _sync_after_change(session)
    LOGGER.info("NVR deleted: %s", nvr_id)
    return ApiResponse(success=True, data={"deleted": True})


@router.post("/nvrs/check-ip", summary="Check if an IP has DVRIP or RTSP ports open")
async def check_nvr_ip(
    body: CheckIpRequest,
    _any: None = Depends(require_any),
) -> ApiResponse:
    has_dvrip = False
    has_rtsp = False

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(body.ip, body.port), timeout=1.0
        )
        writer.close()
        await writer.wait_closed()
        has_dvrip = True
    except Exception:
        pass

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(body.ip, 554), timeout=1.0
        )
        writer.close()
        await writer.wait_closed()
        has_rtsp = True
    except Exception:
        pass

    return ApiResponse(
        success=True,
        data=CheckIpResponse(
            ip=body.ip,
            reachable=has_dvrip or has_rtsp,
            has_dvrip=has_dvrip,
            has_rtsp=has_rtsp,
        ).model_dump(mode="json"),
    )


@router.post("/nvrs/discover", summary="xMEye-style: enter IP, discover all cameras on NVR")
async def discover_nvr(
    body: NvrDiscoverRequest,
    _any: None = Depends(require_any),
) -> ApiResponse:
    """Discover NVR device info and active channels.

    Flow: TCP connect -> DVRIP login (get channel count) -> probe each channel.
    Returns NVR info + list of active channels with their status.
    """
    loop = asyncio.get_event_loop()

    # Step 1: Get channel count via DVRIP login
    channel_count = await loop.run_in_executor(
        None,
        NvrDiscoveryService._dvrip_get_channel_count,
        body.ip, body.port, body.username, body.password,
    )

    if channel_count is None:
        return ApiResponse(
            success=False,
            error={
                "code": "CONNECTION_FAILED",
                "message": f"Could not connect to DVRIP at {body.ip}:{body.port}. "
                           "Check IP, port, and credentials.",
            },
        )

    # Step 2: Probe each channel for active video
    channels = await loop.run_in_executor(
        None,
        NvrDiscoveryService._scan_dvrip_channels,
        body.ip, body.username, body.password,
    )

    active_channels = [c for c in channels if c.get("active")]

    LOGGER.info(
        "NVR discovered: %s:%d channels=%d active=%d",
        body.ip, body.port, channel_count, len(active_channels),
    )

    return ApiResponse(
        success=True,
        data={
            "nvr_info": {
                "ip": body.ip,
                "port": body.port,
                "channel_count": channel_count,
                "active_count": len(active_channels),
            },
            "all_channels": channels,
            "active_channels": active_channels,
        },
    )


@router.post("/nvrs/discover-broadcast", summary="UDP broadcast discovery for NVRs on local network")
async def discover_nvr_broadcast(
    _any: None = Depends(require_any),
) -> ApiResponse:
    """Send UDP broadcast to find NVRs on the local network.

    Uses the DVRIP UDP discovery protocol (port 34569) to find NVRs.
    """
    from cv_engine.services.dvrip_client import DVRIPClient

    loop = asyncio.get_event_loop()
    devices = await loop.run_in_executor(
        None,
        DVRIPClient.discover_broadcast,
        3.0,
    )

    return ApiResponse(success=True, data=devices)


@router.post("/nvrs/{nvr_id}/import-channels", summary="Import channels from an NVR as cameras")
async def import_nvr_channels(
    nvr_id: uuid.UUID,
    channels: list[int] = Query(..., description="Channel numbers to import"),
    prefer_rtsp: bool = Query(True, description="Prefer RTSP over DVRIP if available"),
    _admin: None = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    nvr = await session.get(Nvr, nvr_id)
    if not nvr:
        return ApiResponse(success=False, error={"code": "NOT_FOUND", "message": "NVR not found"})

    # Probe RTSP availability once for the NVR
    has_rtsp = False
    if prefer_rtsp:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(nvr.ip_address, 554), timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            has_rtsp = True
            LOGGER.info("NVR %s has RTSP on port 554 — will use RTSP URLs", nvr.ip_address)
        except Exception:
            LOGGER.info("NVR %s RTSP not available — falling back to DVRIP", nvr.ip_address)

    cam_service = CameraService(session)
    imported = []
    for ch in channels:
        stream_url = _build_stream_url(nvr, ch, prefer_rtsp=has_rtsp)
        cam = await cam_service.create_or_update(
            warehouse_id=nvr.warehouse_id,
            camera_name=f"{nvr.name} Ch{ch}",
            stream_url=stream_url,
            status="active",
            nvr_id=nvr.id,
        )
        imported.append({
            "id": str(cam.id),
            "camera_name": cam.camera_name,
            "stream_url": cam.stream_url,
            "channel": ch,
            "protocol": "rtsp" if has_rtsp else "dvrip",
        })

    await _sync_after_change(session)

    LOGGER.info("NVR %s: imported %d channels (protocol=%s)", nvr_id, len(imported), "rtsp" if has_rtsp else "dvrip")
    return ApiResponse(
        success=True,
        data={"imported": imported, "nvr_id": str(nvr_id), "count": len(imported), "protocol": "rtsp" if has_rtsp else "dvrip"},
    )
