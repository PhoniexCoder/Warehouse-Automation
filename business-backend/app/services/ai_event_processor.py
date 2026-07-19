from datetime import datetime, timezone
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertType, AlertSeverity
from app.models.box import BoxStatus
from app.models.count_log import MovementType
from app.schemas.ai_event import MovementTypeEnum
from app.services.audit_service import AuditService
from app.services.box_service import BoxService
from app.services.count_log_service import CountLogService
from app.services.alert_service import AlertService
from app.services.inventory_service import InventoryService

LOGGER = logging.getLogger(__name__)


class AiEventProcessor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._boxes = BoxService(session)
        self._count_logs = CountLogService(session)
        self._alerts = AlertService(session)
        self._audit = AuditService(session)
        self._inventory = InventoryService(session)

    async def process_detection(
        self,
        tracking_id: int,
        camera_id: str,
        counted: bool,
        qr_data: str | None = None,
        movement_type: MovementTypeEnum = MovementTypeEnum.ENTRY,
        timestamp: datetime | None = None,
    ) -> dict:
        ts = timestamp or datetime.now(timezone.utc)

        box = await self._boxes.get_or_create(
            tracking_id=tracking_id,
            camera_id=camera_id,
            qr_data=qr_data,
        )

        if counted:
            db_movement = MovementType.ENTRY if movement_type == MovementTypeEnum.ENTRY else MovementType.EXIT

            await self._count_logs.record(
                box_id=box.id,
                camera_id=camera_id,
                movement_type=db_movement,
                timestamp=ts,
            )

            if movement_type == MovementTypeEnum.ENTRY:
                box.status = BoxStatus.STORED
            else:
                box.status = BoxStatus.DISPATCHED

            await self._session.flush()

            await self._sync_inventory(qr_data, camera_id, movement_type)

            LOGGER.info(
                "Box counted (%s): tracking_id=%s qr=%s",
                movement_type.value, tracking_id, qr_data,
            )

        await self._audit.log(
            action=(
                f"detection.received.camera={camera_id}."
                f"tracking={tracking_id}.counted={counted}."
                f"movement={movement_type.value}"
            ),
        )

        return {
            "box_id": str(box.id),
            "tracking_id": tracking_id,
            "counted": counted,
            "movement_type": movement_type.value,
        }

    async def _sync_inventory(
        self,
        qr_data: str | None,
        camera_id: str,
        movement_type: MovementTypeEnum,
    ) -> None:
        if not qr_data:
            return

        item = await self._inventory.find_inventory_by_qr(qr_data)
        if item:
            if movement_type == MovementTypeEnum.ENTRY:
                await self._inventory.increment_inventory(item.id)
            else:
                await self._inventory.decrement_inventory(item.id)
            LOGGER.info(
                "Inventory synced: %s qr=%s (%s)",
                item.product_code, qr_data, movement_type.value,
            )
        else:
            await self._inventory.create_inventory_alert(
                qr_data=qr_data,
                camera_id=camera_id,
                details=f"Movement={movement_type.value}",
            )

    async def process_invalid_qr(
        self,
        tracking_id: int,
        error_type: str,
        camera_id: str,
        timestamp: datetime | None = None,
    ) -> dict:
        ts = timestamp or datetime.now(timezone.utc)

        box = await self._boxes.get_or_create(
            tracking_id=tracking_id,
            camera_id=camera_id,
        )

        await self._alerts.create(
            alert_type=AlertType.INVALID_QR,
            severity=AlertSeverity.WARNING,
            message=f"Invalid QR ({error_type}) for tracking_id={tracking_id} at camera={camera_id}",
        )

        await self._audit.log(
            action=f"invalid_qr.received.camera={camera_id}.tracking={tracking_id}.error={error_type}",
        )

        LOGGER.info("Invalid QR: tracking_id=%s error=%s camera=%s",
                     tracking_id, error_type, camera_id)

        return {
            "box_id": str(box.id),
            "tracking_id": tracking_id,
            "alert_generated": True,
        }
