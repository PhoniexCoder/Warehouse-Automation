import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)


class DuplicateGuard:
    def __init__(self) -> None:
        self._track_ids: set[int] = set()
        self._qr_codes: set[str] = set()

    def is_new(self, track_id: int, qr_data: Optional[str] = None) -> bool:
        if track_id in self._track_ids:
            return False
        if qr_data and qr_data in self._qr_codes:
            return False
        return True

    def mark_counted(self, track_id: int, qr_data: Optional[str] = None) -> None:
        self._track_ids.add(track_id)
        if qr_data:
            self._qr_codes.add(qr_data)
