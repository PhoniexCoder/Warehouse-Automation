import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertType, AlertSeverity

LOGGER = logging.getLogger(__name__)


class AlertService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
    ) -> Alert:
        alert = Alert(type=alert_type, severity=severity, message=message)
        self._session.add(alert)
        await self._session.flush()
        LOGGER.info("Alert: [%s] %s", severity.value, message)
        return alert

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        alert_type: AlertType | None = None,
        severity: AlertSeverity | None = None,
    ) -> list[Alert]:
        stmt = select(Alert).order_by(Alert.timestamp.desc())
        if alert_type is not None:
            stmt = stmt.where(Alert.type == alert_type)
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_all(self) -> int:
        stmt = select(func.count(Alert.id))
        result = await self._session.execute(stmt)
        return result.scalar() or 0
