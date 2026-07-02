import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.alert import AlertType, AlertSeverity
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.alert import AlertResponse
from app.services.alert_service import AlertService
from app.auth.permissions import require_manager_up

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Alerts"])


@router.get("/alerts", summary="List alerts")
async def list_alerts(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    alert_type: str | None = None,
    severity: str | None = None,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = AlertService(session)
    type_enum = AlertType(alert_type) if alert_type else None
    severity_enum = AlertSeverity(severity) if severity else None
    alerts = await service.list_all(
        limit=limit, offset=offset, alert_type=type_enum, severity=severity_enum,
    )
    return ApiResponse(
        success=True,
        data=[AlertResponse.model_validate(a).model_dump(mode="json") for a in alerts],
    )
