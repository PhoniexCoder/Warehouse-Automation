import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)


class DuplicateGuard:
    def __init__(self) -> None:
        self._track_ids: set[int] = set()
        self._qr_codes: set[str] = set()

    @property
    def counted_track_count(self) -> int:
        return len(self._track_ids)

    @property
    def counted_qr_count(self) -> int:
        return len(self._qr_codes)

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

    def is_track_counted(self, track_id: int) -> bool:
        return track_id in self._track_ids

    def is_qr_counted(self, qr_data: str) -> bool:
        return qr_data in self._qr_codes

    def load_existing(self, track_ids: set[int], qr_codes: set[str]) -> None:
        self._track_ids.update(track_ids)
        self._qr_codes.update(qr_codes)
        LOGGER.info(
            "Loaded %d track_ids and %d QR codes into DuplicateGuard",
            len(track_ids), len(qr_codes),
        )

    def reset(self) -> None:
        self._track_ids.clear()
        self._qr_codes.clear()
        LOGGER.info("DuplicateGuard reset")
