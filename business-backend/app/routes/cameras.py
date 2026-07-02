import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.common import ApiResponse
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse
from app.services.camera_service import CameraService
from app.services.audit_service import AuditService
from app.auth.permissions import require_admin, require_any
from app.models.user import User

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Cameras"])


@router.post("/cameras", status_code=201, summary="Register a camera")
async def create_camera(
    body: CameraCreate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    audit = AuditService(session)
    camera = await service.create(
        warehouse_id=body.warehouse_id,
        camera_name=body.camera_name,
        stream_url=body.stream_url,
        status=body.status,
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
    return ApiResponse(
        success=True,
        data=[CameraResponse.model_validate(c).model_dump(mode="json") for c in cameras],
    )


@router.get("/cameras/{camera_uuid}", summary="Get camera by ID")
async def get_camera(
    camera_uuid: uuid.UUID,
    _any: User = Depends(require_any),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    camera = await service.get(camera_uuid)
    return ApiResponse(
        success=True,
        data=CameraResponse.model_validate(camera).model_dump(mode="json"),
    )


@router.put("/cameras/{camera_uuid}", summary="Update a camera")
async def update_camera(
    camera_uuid: uuid.UUID,
    body: CameraUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    audit = AuditService(session)
    camera = await service.update(
        camera_uuid,
        camera_name=body.camera_name,
        stream_url=body.stream_url,
        status=body.status,
    )
    await audit.log(action="camera.updated")
    return ApiResponse(
        success=True,
        data=CameraResponse.model_validate(camera).model_dump(mode="json"),
    )


@router.delete("/cameras/{camera_uuid}", summary="Delete a camera")
async def delete_camera(
    camera_uuid: uuid.UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CameraService(session)
    audit = AuditService(session)
    await service.delete(camera_uuid)
    await audit.log(action="camera.deleted")
    return ApiResponse(success=True, data={"deleted": True})
