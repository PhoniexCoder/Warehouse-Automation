import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)

NO_QR = "NO_QR"
INVALID_QR = "INVALID_QR"
DAMAGED_QR = "DAMAGED_QR"


class InvalidQrHandler:
    def __init__(self) -> None:
        self._statuses: dict[int, str] = {}

    def get_status(self, track_id: int, has_qr: bool, qr_data: Optional[str]) -> Optional[str]:
        if has_qr and qr_data:
            return None

        status = self._statuses.get(track_id)
        if status is not None:
            return status

        if qr_data is None and not has_qr:
            status = NO_QR
        else:
            status = INVALID_QR

        self._statuses[track_id] = status
        LOGGER.debug("track_id=%s status=%s", track_id, status)
        return status

    def get_all_statuses(self) -> dict[int, str]:
        return dict(self._statuses)

    def clear(self) -> None:
        self._statuses.clear()
