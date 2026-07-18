import os
import uuid
import logging
import asyncio
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SETTINGS
from app.database.session import get_session
from app.schemas.common import ApiResponse
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse, VmsScanRequest, VmsImportRequest, DvripConnectRequest
from app.services.camera_service import CameraService
from app.services.audit_service import AuditService
from app.auth.permissions import require_manager_up, require_any
from app.models.user import User

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Cameras"])


@router.post("/cameras", status_code=201, summary="Register a camera")
async def create_camera(
    body: CameraCreate,
    _admin: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    audit = AuditService(session)
    camera = await service.create(
        warehouse_id=body.warehouse_id,
        camera_name=body.camera_name,
        stream_url=body.stream_url,
        status=body.status,
        model_path=body.model_path,
        roi=body.roi,
    )
    await audit.log(action="camera.created")
    return ApiResponse(
        success=True,
        data=CameraResponse.model_validate(camera).model_dump(mode="json"),
    )


@router.get("/cameras", summary="List cameras")
async def list_cameras(
    warehouse_id: uuid.UUID | None = None,
    _any: User = Depends(require_any),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    cameras = await service.list_by_warehouse(warehouse_id) if warehouse_id else await service.list_all()

    ai_status = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{SETTINGS.ai_engine_url}/api/v1/cameras")
            if resp.status_code == 200:
                ai_status = resp.json().get("data", {}).get("cameras", {})
    except Exception as exc:
        LOGGER.warning("Failed to fetch camera health from AI Engine: %s", exc)

    data = []
    for c in cameras:
        c_res = CameraResponse.model_validate(c).model_dump(mode="json")
        cam_id_str = str(c.id)
        if cam_id_str in ai_status:
            c_res["health"] = ai_status[cam_id_str].get("health")
        else:
            c_res["health"] = None
        data.append(c_res)

    return ApiResponse(
        success=True,
        data=data,
    )


@router.get("/cameras/{camera_uuid}", summary="Get camera by ID")
async def get_camera(
    camera_uuid: uuid.UUID,
    _any: User = Depends(require_any),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    camera = await service.get(camera_uuid)

    ai_status = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{SETTINGS.ai_engine_url}/api/v1/cameras")
            if resp.status_code == 200:
                ai_status = resp.json().get("data", {}).get("cameras", {})
    except Exception as exc:
        LOGGER.warning("Failed to fetch camera health from AI Engine: %s", exc)

    c_res = CameraResponse.model_validate(camera).model_dump(mode="json")
    cam_id_str = str(camera.id)
    if cam_id_str in ai_status:
        c_res["health"] = ai_status[cam_id_str].get("health")
    else:
        c_res["health"] = None

    return ApiResponse(
        success=True,
        data=c_res,
    )


@router.put("/cameras/{camera_uuid}", summary="Update a camera")
async def update_camera(
    camera_uuid: uuid.UUID,
    body: CameraUpdate,
    _admin: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    audit = AuditService(session)

    update_fields = {}
    for field_name in body.model_fields_set:
        update_fields[field_name] = getattr(body, field_name)

    camera = await service.update(camera_uuid, **update_fields)
    await audit.log(action="camera.updated")
    return ApiResponse(
        success=True,
        data=CameraResponse.model_validate(camera).model_dump(mode="json"),
    )


@router.delete("/cameras/{camera_uuid}", summary="Delete a camera")
async def delete_camera(
    camera_uuid: uuid.UUID,
    _admin: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    audit = AuditService(session)
    await service.delete(camera_uuid)
    await audit.log(action="camera.deleted")
    return ApiResponse(success=True, data={"deleted": True})


@router.get("/vms/discover", summary="Discover NVRs and cameras on local network")
async def discover_vms(
    _any: User = Depends(require_any),
) -> ApiResponse:
    from app.services.nvr_discovery import NvrDiscoveryService
    devices = await NvrDiscoveryService.discover_devices()
    return ApiResponse(success=True, data=devices)


@router.post("/vms/scan-channels", summary="Scan active RTSP channels on a discovered NVR")
async def scan_vms_channels(
    body: VmsScanRequest,
    _any: User = Depends(require_any),
) -> ApiResponse:
    from app.services.nvr_discovery import NvrDiscoveryService
    channels = await NvrDiscoveryService.scan_active_channels(
        ip=body.ip,
        username=body.username,
        password=body.password
    )
    return ApiResponse(success=True, data=channels)


@router.post("/vms/import", summary="Auto-import active channels from an NVR")
async def import_vms_cameras(
    body: VmsImportRequest,
    _admin: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    from app.services.nvr_discovery import NvrDiscoveryService
    service = CameraService(session)
    audit = AuditService(session)

    # Detect if the NVR supports DVRIP (port 34567)
    has_dvrip = False
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(body.ip, 34567), timeout=0.5
        )
        writer.close()
        await writer.wait_closed()
        has_dvrip = True
    except Exception:
        pass

    imported = []
    for ch in body.channels:
        if has_dvrip:
            stream_url = f"dvrip://{body.username}:{body.password}@{body.ip}:34567/{ch}"
        else:
            stream_url = f"rtsp://{body.username}:{body.password}@{body.ip}:554/user={body.username}&password={body.password}&channel={ch}&stream=1.sdp?"
        camera_name = f"NVR {body.ip} Channel {ch}"
        
        camera = await service.create(
            warehouse_id=body.warehouse_id,
            camera_name=camera_name,
            stream_url=stream_url,
            status="active"
        )
        imported.append(CameraResponse.model_validate(camera).model_dump(mode="json"))
        
    await audit.log(action="camera.vms_imported")
    return ApiResponse(success=True, data={"imported": imported})


@router.post("/vms/dvrip-connect", summary="Connect to NVR via DVRIP and auto-import all channels")
async def dvrip_connect(
    body: DvripConnectRequest,
    _admin: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    """One-click DVRIP setup: enter host/credentials, imports all 16 channels as dvrip:// URLs.
    The AI backend auto-detects dvrip:// and starts streaming via native DVRIP protocol."""
    service = CameraService(session)
    audit = AuditService(session)

    imported = []
    for ch in range(1, 17):
        stream_url = f"dvrip://{body.username}:{body.password}@{body.host}:34567/{ch}"
        camera_name = f"DVRIP {body.host} Ch{ch}"

        camera = await service.create(
            warehouse_id=body.warehouse_id,
            camera_name=camera_name,
            stream_url=stream_url,
            status="active",
        )
        imported.append(CameraResponse.model_validate(camera).model_dump(mode="json"))

    await audit.log(action="camera.dvrip_connected")
    return ApiResponse(
        success=True,
        data={
            "imported": imported,
            "host": body.host,
            "channels": len(imported),
            "protocol": "dvrip",
        },
    )


@router.get("/cameras/internal/active", summary="List active cameras (Internal use)")
async def list_active_cameras_internal(
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    cameras = await service.list_all()
    active = [c for c in cameras if c.status == "active" or c.status == "online"]
    return ApiResponse(
        success=True,
        data=[CameraResponse.model_validate(c).model_dump(mode="json") for c in active],
    )


GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://host.docker.internal:1984")


@router.get("/go2rtc/streams", summary="List available go2rtc streams")
async def list_go2rtc_streams(
    _any: User = Depends(require_any),
) -> ApiResponse:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{GO2RTC_URL}/api/streams")
            resp.raise_for_status()
            return ApiResponse(success=True, data=resp.json())
    except Exception as exc:
        LOGGER.warning("Failed to reach go2rtc: %s", exc)
        return ApiResponse(success=True, data={})


MODEL_DIRS = [
    Path(os.getenv("MODEL_DIR", "models")),
    Path("/app/models"),
]


@router.get("/models", summary="List available ML model files")
async def list_models() -> ApiResponse:
    models = []
    seen = set()
    for d in MODEL_DIRS:
        if not d.is_dir():
            continue
        for pt in sorted(d.glob("*.pt")):
            resolved = str(pt.resolve())
            if resolved not in seen:
                seen.add(resolved)
                models.append({
                    "path": resolved,
                    "name": pt.stem,
                    "size_bytes": pt.stat().st_size,
                })
    return ApiResponse(success=True, data=models)
