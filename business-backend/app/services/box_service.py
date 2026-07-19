import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.box import Box, BoxStatus

LOGGER = logging.getLogger(__name__)


class BoxService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        tracking_id: int,
        camera_id: str,
        qr_data: str | None = None,
    ) -> Box:
        stmt = (
            select(Box)
            .where(Box.tracking_id == tracking_id, Box.camera_id == str(camera_id))
            .limit(1)
        )
        result = await self._session.execute(stmt)
        box = result.scalar_one_or_none()

        if box:
            if qr_data and not box.qr_data:
                box.qr_data = qr_data
            await self._session.flush()
            return box

        box = Box(
            tracking_id=tracking_id,
            qr_data=qr_data,
            camera_id=camera_id,
            status=BoxStatus.IN_TRANSIT,
        )
        self._session.add(box)
        await self._session.flush()
        LOGGER.info("Box created: tracking_id=%s", tracking_id)
        return box

    async def get(self, box_id: uuid.UUID) -> Box:
        box = await self._session.get(Box, box_id)
        if not box:
            raise NotFoundError("Box", str(box_id))
        return box

    async def get_by_tracking_id(self, tracking_id: int) -> Box | None:
        stmt = select(Box).where(Box.tracking_id == tracking_id).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_qr(self, qr_data: str) -> list[Box]:
        stmt = (
            select(Box)
            .where(Box.qr_data == qr_data)
            .order_by(Box.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status: BoxStatus | None = None,
        camera_id: str | None = None,
    ) -> list[Box]:
        stmt = select(Box).order_by(Box.created_at.desc())
        if status:
            stmt = stmt.where(Box.status == status)
        if camera_id:
            stmt = stmt.where(Box.camera_id == camera_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
