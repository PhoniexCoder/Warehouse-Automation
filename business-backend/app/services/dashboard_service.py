import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.warehouse import Warehouse
from app.models.camera import Camera
from app.models.box import Box
from app.models.inventory import Inventory
from app.models.count_log import CountLog, MovementType
from app.models.alert import Alert

LOGGER = logging.getLogger(__name__)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self) -> dict:
        warehouse_count = await self._count(Warehouse.id, Warehouse)
        camera_count = await self._count(Camera.id, Camera)
        box_count = await self._count(Box.id, Box)
        inventory_count = await self._count(Inventory.id, Inventory)
        count_log_count = await self._count(CountLog.id, CountLog)
        alert_count = await self._count(Alert.id, Alert)

        entry_count = await self._count_filtered(
            CountLog.id, CountLog, CountLog.movement_type == MovementType.ENTRY
        )
        exit_count = await self._count_filtered(
            CountLog.id, CountLog, CountLog.movement_type == MovementType.EXIT
        )

        return {
            "total_warehouses": warehouse_count,
            "total_cameras": camera_count,
            "total_boxes": box_count,
            "total_inventory_items": inventory_count,
            "total_count_logs": count_log_count,
            "total_alerts": alert_count,
            "entry_count": entry_count,
            "exit_count": exit_count,
        }

    async def _count(self, column, model) -> int:
        stmt = select(func.count(column)).select_from(model)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def _count_filtered(self, column, model, *filters) -> int:
        stmt = select(func.count(column)).select_from(model).where(*filters)
        result = await self._session.execute(stmt)
        return result.scalar() or 0
