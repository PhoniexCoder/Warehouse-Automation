import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.user import User
from app.schemas.common import ApiResponse
from app.services.dashboard_service import DashboardService
from app.auth.permissions import require_manager_up

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/summary", summary="Aggregated dashboard statistics")
async def dashboard_summary(
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = DashboardService(session)
    summary = await service.summary()
    return ApiResponse(success=True, data=summary)
