import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.camera import Camera, CameraStatus

LOGGER = logging.getLogger(__name__)


class CameraService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        warehouse_id: uuid.UUID,
        camera_name: str,
        stream_url: str,
        status: str | None = None,
        model_path: str | None = None,
        roi: dict | list | None = None,
    ) -> Camera:
        camera = Camera(
            warehouse_id=warehouse_id,
            camera_name=camera_name,
            stream_url=stream_url,
            status=CameraStatus(status) if status else CameraStatus.ACTIVE,
            model_path=model_path,
            roi=roi,
        )
        self._session.add(camera)
        await self._session.flush()
        LOGGER.info("Camera created: %s (%s)", camera.id, camera_name)
        return camera

    async def get(self, camera_uuid: uuid.UUID) -> Camera:
        camera = await self._session.get(Camera, camera_uuid)
        if not camera:
            raise NotFoundError("Camera", str(camera_uuid))
        return camera

    async def update(self, camera_uuid: uuid.UUID, **kwargs) -> Camera:
        camera = await self.get(camera_uuid)
        for key, value in kwargs.items():
            if value is not None and hasattr(camera, key):
                if key == "status":
                    value = CameraStatus(value)
                setattr(camera, key, value)
        await self._session.flush()
        LOGGER.info("Camera updated: %s", camera_uuid)
        return camera

    async def delete(self, camera_uuid: uuid.UUID) -> None:
        camera = await self.get(camera_uuid)
        await self._session.delete(camera)
        await self._session.flush()
        LOGGER.info("Camera deleted: %s", camera_uuid)

    async def list_by_warehouse(self, warehouse_id: uuid.UUID) -> list[Camera]:
        stmt = (
            select(Camera)
            .where(Camera.warehouse_id == warehouse_id)
            .order_by(Camera.camera_name)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[Camera]:
        stmt = select(Camera).order_by(Camera.camera_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
