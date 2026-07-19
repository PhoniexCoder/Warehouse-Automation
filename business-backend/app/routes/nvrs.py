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
)
from app.models.nvr import Nvr
from app.models.camera import Camera, CameraStatus
from app.auth.permissions import require_manager_up, require_any
from app.services.go2rtc_config import sync_cameras

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


def _build_stream_url(nvr: Nvr, channel: int) -> str:
    """Build the dvrip:// stream URL for a camera channel on this NVR."""
    cred = ""
    if nvr.username:
        cred = f"{nvr.username}:{nvr.password or ''}@"
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


@router.post("/nvrs/{nvr_id}/import-channels", summary="Import channels from an NVR as cameras")
async def import_nvr_channels(
    nvr_id: uuid.UUID,
    channels: list[int] = Query(..., description="Channel numbers to import"),
    _admin: None = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    nvr = await session.get(Nvr, nvr_id)
    if not nvr:
        return ApiResponse(success=False, error={"code": "NOT_FOUND", "message": "NVR not found"})

    imported = []
    for ch in channels:
        stream_url = _build_stream_url(nvr, ch)
        cam = Camera(
            warehouse_id=nvr.warehouse_id,
            camera_name=f"{nvr.name} Ch{ch}",
            stream_url=stream_url,
            status=CameraStatus.ACTIVE,
            nvr_id=nvr.id,
        )
        session.add(cam)
        await session.flush()
        imported.append({
            "id": str(cam.id),
            "camera_name": cam.camera_name,
            "stream_url": cam.stream_url,
            "channel": ch,
        })

    await _sync_after_change(session)

    LOGGER.info("NVR %s: imported %d channels", nvr_id, len(imported))
    return ApiResponse(
        success=True,
        data={"imported": imported, "nvr_id": str(nvr_id), "count": len(imported)},
    )
