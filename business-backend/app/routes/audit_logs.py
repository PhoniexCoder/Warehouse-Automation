import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.audit_log import AuditLogResponse
from app.services.audit_service import AuditService
from app.auth.permissions import require_admin

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Audit Logs"])


@router.get("/audit-logs", summary="List audit log entries")
async def list_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_id: str | None = None,
    action: str | None = None,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = AuditService(session)
    logs = await service.list_logs(
        limit=limit, offset=offset, user_id=user_id, action=action,
    )
    return ApiResponse(
        success=True,
        data=[AuditLogResponse.model_validate(log).model_dump(mode="json") for log in logs],
    )
