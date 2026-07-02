import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.inventory import Inventory
from app.models.alert import Alert, AlertType, AlertSeverity

LOGGER = logging.getLogger(__name__)


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        product_code: str,
        product_name: str,
        quantity: int,
        warehouse_id: uuid.UUID,
    ) -> Inventory:
        existing = await self._get_by_code(product_code)
        if existing:
            raise ConflictError(f"Product already exists: {product_code}")
        item = Inventory(
            product_code=product_code,
            product_name=product_name,
            quantity=quantity,
            warehouse_id=warehouse_id,
        )
        self._session.add(item)
        await self._session.flush()
        LOGGER.info("Inventory created: %s (%s)", product_code, product_name)
        return item

    async def get(self, item_id: uuid.UUID) -> Inventory:
        item = await self._session.get(Inventory, item_id)
        if not item:
            raise NotFoundError("Inventory", str(item_id))
        return item

    async def update(
        self,
        item_id: uuid.UUID,
        product_name: str | None = None,
        quantity: int | None = None,
    ) -> Inventory:
        item = await self.get(item_id)
        if product_name is not None:
            item.product_name = product_name
        if quantity is not None:
            item.quantity = quantity
        await self._session.flush()
        LOGGER.info("Inventory updated: %s", item_id)
        return item

    async def delete(self, item_id: uuid.UUID) -> None:
        item = await self.get(item_id)
        await self._session.delete(item)
        await self._session.flush()
        LOGGER.info("Inventory deleted: %s", item_id)

    async def list_by_warehouse(self, warehouse_id: uuid.UUID) -> list[Inventory]:
        stmt = (
            select(Inventory)
            .where(Inventory.warehouse_id == warehouse_id)
            .order_by(Inventory.product_code)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[Inventory]:
        stmt = select(Inventory).order_by(Inventory.product_code)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_inventory_by_qr(self, qr_data: str) -> Inventory | None:
        stmt = select(Inventory).where(Inventory.product_code == qr_data)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_inventory(
        self, item_id: uuid.UUID, quantity: int = 1,
    ) -> Inventory:
        item = await self.get(item_id)
        item.quantity += quantity
        await self._session.flush()
        LOGGER.info(
            "Inventory incremented: %s (+%d) = %d",
            item.product_code, quantity, item.quantity,
        )
        return item

    async def decrement_inventory(
        self, item_id: uuid.UUID, quantity: int = 1,
    ) -> Inventory:
        item = await self.get(item_id)
        if item.quantity < quantity:
            LOGGER.warning(
                "Inventory underflow: %s (%d < %d)",
                item.product_code, item.quantity, quantity,
            )
        item.quantity = max(0, item.quantity - quantity)
        await self._session.flush()
        LOGGER.info(
            "Inventory decremented: %s (-%d) = %d",
            item.product_code, quantity, item.quantity,
        )
        return item

    async def create_inventory_alert(
        self, qr_data: str, camera_id: str, details: str | None = None,
    ) -> Alert:
        message = (
            f"Inventory mismatch: QR '{qr_data}' not found in database "
            f"(camera={camera_id})"
        )
        if details:
            message = f"{message}. {details}"
        alert = Alert(
            type=AlertType.INVENTORY_MISMATCH,
            severity=AlertSeverity.WARNING,
            message=message,
        )
        self._session.add(alert)
        await self._session.flush()
        LOGGER.warning(
            "Inventory alert created: QR=%s camera=%s", qr_data, camera_id,
        )
        return alert

    async def _get_by_code(self, product_code: str) -> Inventory | None:
        stmt = select(Inventory).where(Inventory.product_code == product_code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
