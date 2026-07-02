import uuid
from datetime import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.movement import Movement

LOGGER = logging.getLogger(__name__)


class MovementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        inventory_item_id: uuid.UUID,
        warehouse_id: uuid.UUID | None,
        camera_id: uuid.UUID | None,
        tracking_id: int,
        qr_data: str | None,
        event_type: str,
        counted: bool,
        timestamp: datetime,
        box_x: int = 0,
        box_y: int = 0,
        box_width: int = 0,
        box_height: int = 0,
    ) -> Movement:
        movement = Movement(
            inventory_item_id=inventory_item_id,
            warehouse_id=warehouse_id,
            camera_id=camera_id,
            tracking_id=tracking_id,
            qr_data=qr_data,
            event_type=event_type,
            counted=counted,
            timestamp=timestamp,
            box_x=box_x,
            box_y=box_y,
            box_width=box_width,
            box_height=box_height,
        )
        self._session.add(movement)
        await self._session.flush()
        LOGGER.debug("Movement recorded: %s %s", event_type, tracking_id)
        return movement

    async def get(self, movement_id: uuid.UUID) -> Movement:
        movement = await self._session.get(Movement, movement_id)
        if not movement:
            raise NotFoundError("Movement", str(movement_id))
        return movement

    async def list_by_inventory(self, inventory_item_id: uuid.UUID) -> list[Movement]:
        stmt = (
            select(Movement)
            .where(Movement.inventory_item_id == inventory_item_id)
            .order_by(Movement.timestamp.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_tracking(self, tracking_id: int) -> list[Movement]:
        stmt = (
            select(Movement)
            .where(Movement.tracking_id == tracking_id)
            .order_by(Movement.timestamp.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        tracking_id: int | None = None,
        warehouse_id: uuid.UUID | None = None,
        camera_id: uuid.UUID | None = None,
        event_type: str | None = None,
        counted: bool | None = None,
    ) -> list[Movement]:
        stmt = select(Movement).order_by(Movement.timestamp.desc())
        if tracking_id is not None:
            stmt = stmt.where(Movement.tracking_id == tracking_id)
        if warehouse_id is not None:
            stmt = stmt.where(Movement.warehouse_id == warehouse_id)
        if camera_id is not None:
            stmt = stmt.where(Movement.camera_id == camera_id)
        if event_type is not None:
            stmt = stmt.where(Movement.event_type == event_type)
        if counted is not None:
            stmt = stmt.where(Movement.counted == counted)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_all(self) -> int:
        stmt = select(func.count(Movement.id))
        result = await self._session.execute(stmt)
        return result.scalar() or 0
