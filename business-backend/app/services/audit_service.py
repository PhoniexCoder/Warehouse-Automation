import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

LOGGER = logging.getLogger(__name__)


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        action: str,
        user_id: str | None = None,
    ) -> AuditLog:
        record = AuditLog(user_id=user_id, action=action)
        self._session.add(record)
        await self._session.flush()
        LOGGER.info("Audit: %s (user=%s)", action, user_id)
        return record

    async def list_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None = None,
        action: str | None = None,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.timestamp.desc())
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
