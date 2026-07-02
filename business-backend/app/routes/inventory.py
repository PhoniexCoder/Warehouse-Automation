import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.inventory import (
    InventoryCreate,
    InventoryUpdate,
    InventoryResponse,
    InventorySyncRequest,
    InventorySyncResponse,
    SyncMovementTypeEnum,
)
from app.services.inventory_service import InventoryService
from app.services.audit_service import AuditService
from app.auth.permissions import require_admin, require_manager_up

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Inventory"])


@router.post("/inventory/sync", status_code=200, summary="Sync inventory from QR scan")
async def sync_inventory(
    body: InventorySyncRequest,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = InventoryService(session)
    audit = AuditService(session)

    item = await service.find_inventory_by_qr(body.qr_data)

    if item:
        qty_before = item.quantity
        if body.movement_type == SyncMovementTypeEnum.ENTRY:
            updated = await service.increment_inventory(item.id)
        else:
            updated = await service.decrement_inventory(item.id)

        await audit.log(
            action=(
                f"inventory.synced.qr={body.qr_data}."
                f"movement={body.movement_type.value}."
                f"before={qty_before}.after={updated.quantity}"
            ),
        )

        return ApiResponse(
            success=True,
            data=InventorySyncResponse(
                matched=True,
                product_code=updated.product_code,
                product_name=updated.product_name,
                quantity_before=qty_before,
                quantity_after=updated.quantity,
                alert_generated=False,
                movement_type=body.movement_type.value,
            ).model_dump(),
        )

    alert = await service.create_inventory_alert(
        qr_data=body.qr_data,
        camera_id=body.camera_id,
        details=f"Manual sync: movement={body.movement_type.value}",
    )

    await audit.log(
        action=(
            f"inventory.sync_failed.qr={body.qr_data}."
            f"movement={body.movement_type.value}.alert={alert.id}"
        ),
    )

    return ApiResponse(
        success=True,
        data=InventorySyncResponse(
            matched=False,
            alert_generated=True,
            alert_id=str(alert.id),
            movement_type=body.movement_type.value,
        ).model_dump(),
    )


@router.post("/inventory", status_code=201, summary="Create inventory item")
async def create_inventory(
    body: InventoryCreate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = InventoryService(session)
    audit = AuditService(session)
    item = await service.create(
        product_code=body.product_code,
        product_name=body.product_name,
        quantity=body.quantity,
        warehouse_id=body.warehouse_id,
    )
    await audit.log(action="inventory.created")
    return ApiResponse(
        success=True,
        data=InventoryResponse.model_validate(item).model_dump(mode="json"),
    )


@router.get("/inventory", summary="List inventory")
async def list_inventory(
    warehouse_id: uuid.UUID | None = None,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = InventoryService(session)
    items = await service.list_by_warehouse(warehouse_id) if warehouse_id else await service.list_all()
    return ApiResponse(
        success=True,
        data=[InventoryResponse.model_validate(i).model_dump(mode="json") for i in items],
    )


@router.get("/inventory/{item_id}", summary="Get inventory item")
async def get_inventory(
    item_id: uuid.UUID,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = InventoryService(session)
    item = await service.get(item_id)
    return ApiResponse(
        success=True,
        data=InventoryResponse.model_validate(item).model_dump(mode="json"),
    )


@router.put("/inventory/{item_id}", summary="Update inventory item")
async def update_inventory(
    item_id: uuid.UUID,
    body: InventoryUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = InventoryService(session)
    audit = AuditService(session)
    item = await service.update(
        item_id,
        product_name=body.product_name,
        quantity=body.quantity,
    )
    await audit.log(action="inventory.updated")
    return ApiResponse(
        success=True,
        data=InventoryResponse.model_validate(item).model_dump(mode="json"),
    )


@router.delete("/inventory/{item_id}", summary="Delete inventory item")
async def delete_inventory(
    item_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = InventoryService(session)
    audit = AuditService(session)
    await service.delete(item_id)
    await audit.log(action="inventory.deleted")
    return ApiResponse(success=True, data={"deleted": True})
