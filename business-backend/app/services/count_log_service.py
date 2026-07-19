import uuid
from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.count_log import CountLog, MovementType

LOGGER = logging.getLogger(__name__)


class CountLogService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        box_id: uuid.UUID,
        camera_id: str,
        movement_type: MovementType,
        timestamp: datetime | None = None,
    ) -> CountLog:
        record = CountLog(
            box_id=box_id,
            camera_id=camera_id,
            movement_type=movement_type,
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        LOGGER.debug("CountLog: %s box=%s camera=%s", movement_type.value, box_id, camera_id)
        return record

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        box_id: uuid.UUID | None = None,
        camera_id: str | None = None,
        movement_type: MovementType | None = None,
    ) -> list[CountLog]:
        stmt = select(CountLog).order_by(CountLog.timestamp.desc())
        if box_id is not None:
            stmt = stmt.where(CountLog.box_id == box_id)
        if camera_id is not None:
            stmt = stmt.where(CountLog.camera_id == camera_id)
        if movement_type is not None:
            stmt = stmt.where(CountLog.movement_type == movement_type)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
