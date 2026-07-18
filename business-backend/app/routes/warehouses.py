import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.common import ApiResponse
from app.schemas.warehouse import WarehouseCreate, WarehouseUpdate, WarehouseResponse
from app.services.warehouse_service import WarehouseService
from app.services.audit_service import AuditService
from app.auth.permissions import require_admin, require_manager_up
from app.models.user import User

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Warehouses"])


@router.post("/warehouses", status_code=201, summary="Create a warehouse")
async def create_warehouse(
    body: WarehouseCreate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = WarehouseService(session)
    audit = AuditService(session)
    warehouse = await service.create(name=body.name, location=body.location)
    await audit.log(action="warehouse.created")
    return ApiResponse(
        success=True,
        data=WarehouseResponse.model_validate(warehouse).model_dump(mode="json"),
    )


@router.get("/warehouses", summary="List warehouses")
async def list_warehouses(
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = WarehouseService(session)
    warehouses = await service.list_all()
    return ApiResponse(
        success=True,
        data=[WarehouseResponse.model_validate(w).model_dump(mode="json") for w in warehouses],
    )


@router.get("/warehouses/{warehouse_id}", summary="Get warehouse by ID")
async def get_warehouse(
    warehouse_id: uuid.UUID,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = WarehouseService(session)
    warehouse = await service.get(warehouse_id)
    return ApiResponse(
        success=True,
        data=WarehouseResponse.model_validate(warehouse).model_dump(mode="json"),
    )


@router.delete("/warehouses/{warehouse_id}", summary="Delete a warehouse")
async def delete_warehouse(
    warehouse_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = WarehouseService(session)
    audit = AuditService(session)
    await service.delete(warehouse_id)
    await audit.log(action="warehouse.deleted")
    return ApiResponse(success=True, data={"deleted": True})


@router.put("/warehouses/{warehouse_id}", summary="Update a warehouse")
async def update_warehouse(
    warehouse_id: uuid.UUID,
    body: WarehouseUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = WarehouseService(session)
    audit = AuditService(session)

    update_fields = {}
    for field_name in body.model_fields_set:
        val = getattr(body, field_name)
        if val is not None:
            update_fields[field_name] = val

    warehouse = await service.update(warehouse_id, **update_fields)
    await audit.log(action="warehouse.updated")
    return ApiResponse(
        success=True,
        data=WarehouseResponse.model_validate(warehouse).model_dump(mode="json"),
    )
