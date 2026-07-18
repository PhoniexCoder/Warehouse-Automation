import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.warehouse import Warehouse

LOGGER = logging.getLogger(__name__)


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str, location: str) -> Warehouse:
        existing = await self._get_by_name(name)
        if existing:
            raise ConflictError(f"Warehouse already exists: {name}")
        warehouse = Warehouse(name=name, location=location)
        self._session.add(warehouse)
        await self._session.flush()
        LOGGER.info("Warehouse created: %s (%s)", warehouse.id, name)
        return warehouse

    async def get(self, warehouse_id: uuid.UUID) -> Warehouse:
        warehouse = await self._session.get(Warehouse, warehouse_id)
        if not warehouse:
            raise NotFoundError("Warehouse", str(warehouse_id))
        return warehouse

    async def list_all(self) -> list[Warehouse]:
        stmt = select(Warehouse).order_by(Warehouse.name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, warehouse_id: uuid.UUID) -> None:
        warehouse = await self.get(warehouse_id)
        await self._session.delete(warehouse)
        await self._session.flush()
        LOGGER.info("Warehouse deleted: %s", warehouse_id)

    async def update(self, warehouse_id: uuid.UUID, **kwargs) -> Warehouse:
        warehouse = await self.get(warehouse_id)
        for key, value in kwargs.items():
            if hasattr(warehouse, key) and value is not None:
                setattr(warehouse, key, value)
        await self._session.flush()
        LOGGER.info("Warehouse updated: %s (fields: %s)", warehouse_id, list(kwargs.keys()))
        return warehouse

    async def _get_by_name(self, name: str) -> Warehouse | None:
        stmt = select(Warehouse).where(Warehouse.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
