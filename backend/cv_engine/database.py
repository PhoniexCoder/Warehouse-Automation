import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Boolean,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from cv_engine.config.settings import SETTINGS

LOGGER = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(Integer, nullable=False, index=True)
    qr_data = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    camera_id = Column(String, nullable=False, default="camera_01")
    counted_status = Column(Boolean, nullable=False, default=False)
    box_x = Column(Integer, nullable=False, default=0)
    box_y = Column(Integer, nullable=False, default=0)
    box_width = Column(Integer, nullable=False, default=0)
    box_height = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tracking_id": self.tracking_id,
            "qr_data": self.qr_data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "camera_id": self.camera_id,
            "counted_status": self.counted_status,
            "box_x": self.box_x,
            "box_y": self.box_y,
            "box_width": self.box_width,
            "box_height": self.box_height,
        }

    def __repr__(self) -> str:
        return (
            f"Detection(id={self.id}, tracking_id={self.tracking_id}, "
            f"qr_data={self.qr_data!r}, camera={self.camera_id}, "
            f"counted={self.counted_status})"
        )


class InvalidQrLog(Base):
    __tablename__ = "invalid_qr_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(Integer, nullable=False, index=True)
    error_type = Column(Text, nullable=False, default="NO_QR")
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    camera_id = Column(String, nullable=False, default="camera_01")
    box_x = Column(Integer, nullable=False, default=0)
    box_y = Column(Integer, nullable=False, default=0)
    box_width = Column(Integer, nullable=False, default=0)
    box_height = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"InvalidQrLog(id={self.id}, tracking_id={self.tracking_id}, "
            f"error={self.error_type}, camera={self.camera_id})"
        )


class DuplicateEvent(Base):
    __tablename__ = "duplicate_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_id = Column(Integer, nullable=False, index=True)
    qr_data = Column(String, nullable=True)
    camera_id = Column(String, nullable=False, default="camera_01")
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    box_x = Column(Integer, nullable=False, default=0)
    box_y = Column(Integer, nullable=False, default=0)
    box_width = Column(Integer, nullable=False, default=0)
    box_height = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"DuplicateEvent(id={self.id}, tracking_id={self.tracking_id}, "
            f"camera={self.camera_id})"
        )


NO_QR = "NO_QR"
INVALID_QR = "INVALID_QR"
DAMAGED_QR = "DAMAGED_QR"

_VALID_ERROR_TYPES = frozenset({NO_QR, INVALID_QR, DAMAGED_QR})


def _get_db_path() -> Path:
    data_dir = Path(SETTINGS.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "detections.db"


_engine = None
_SessionLocal = None
_current_db_path: str | None = None


def _get_engine():
    global _engine, _current_db_path
    db_path = str(_get_db_path())
    if _engine is None or db_path != _current_db_path:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        _current_db_path = db_path
    return _engine


def _get_session() -> Session:
    global _SessionLocal
    _SessionLocal = sessionmaker(bind=_get_engine())
    return _SessionLocal()


def reset_database() -> None:
    global _engine, _SessionLocal, _current_db_path
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _current_db_path = None


def create_tables() -> None:
    engine = _get_engine()
    Detection.__table__.create(engine, checkfirst=True)
    InvalidQrLog.__table__.create(engine, checkfirst=True)
    DuplicateEvent.__table__.create(engine, checkfirst=True)


# ---------------------------------------------------------------------------
# Save operations
# ---------------------------------------------------------------------------


def save_detection(
    tracking_id: int,
    qr_data: Optional[str] = None,
    camera_id: str = "camera_01",
    counted_status: bool = True,
    box_x: int = 0,
    box_y: int = 0,
    box_width: int = 0,
    box_height: int = 0,
) -> Detection:
    session = _get_session()
    try:
        record = Detection(
            tracking_id=tracking_id,
            qr_data=qr_data,
            timestamp=datetime.now(timezone.utc),
            camera_id=camera_id,
            counted_status=counted_status,
            box_x=box_x,
            box_y=box_y,
            box_width=box_width,
            box_height=box_height,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        LOGGER.debug("Detection saved: tracking_id=%s qr=%s counted=%s",
                     tracking_id, qr_data, counted_status)
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_invalid_qr(
    tracking_id: int,
    error_type: str = NO_QR,
    camera_id: str = "camera_01",
    box_x: int = 0,
    box_y: int = 0,
    box_width: int = 0,
    box_height: int = 0,
) -> InvalidQrLog:
    if error_type not in _VALID_ERROR_TYPES:
        LOGGER.warning("Unknown error_type=%r — falling back to NO_QR", error_type)
        error_type = NO_QR

    session = _get_session()
    try:
        record = InvalidQrLog(
            tracking_id=tracking_id,
            error_type=error_type,
            camera_id=camera_id,
            timestamp=datetime.now(timezone.utc),
            box_x=box_x,
            box_y=box_y,
            box_width=box_width,
            box_height=box_height,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        LOGGER.warning("Invalid QR logged: tracking_id=%s error_type=%s camera=%s",
                       tracking_id, error_type, camera_id)
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_duplicate_event(
    tracking_id: int,
    qr_data: Optional[str] = None,
    camera_id: str = "camera_01",
    box_x: int = 0,
    box_y: int = 0,
    box_width: int = 0,
    box_height: int = 0,
) -> DuplicateEvent:
    session = _get_session()
    try:
        record = DuplicateEvent(
            tracking_id=tracking_id,
            qr_data=qr_data,
            camera_id=camera_id,
            timestamp=datetime.now(timezone.utc),
            box_x=box_x,
            box_y=box_y,
            box_width=box_width,
            box_height=box_height,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        LOGGER.warning("Duplicate count logged: tracking_id=%s camera=%s",
                       tracking_id, camera_id)
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Query operations — detections
# ---------------------------------------------------------------------------


def get_detection_by_id(detection_id: int) -> Optional[Detection]:
    session = _get_session()
    try:
        return session.get(Detection, detection_id)
    finally:
        session.close()


def get_all_detections(
    limit: int = 100,
    offset: int = 0,
    counted_only: Optional[bool] = None,
) -> list[Detection]:
    session = _get_session()
    try:
        stmt = select(Detection).order_by(Detection.timestamp.desc())
        if counted_only is not None:
            stmt = stmt.where(Detection.counted_status == counted_only)
        stmt = stmt.limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())
    finally:
        session.close()


def detection_exists(tracking_id: int) -> bool:
    session = _get_session()
    try:
        result = session.execute(
            select(Detection).where(
                Detection.tracking_id == tracking_id,
                Detection.counted_status == True,
            ).limit(1)
        ).scalar_one_or_none()
        return result is not None
    finally:
        session.close()


def get_total_count() -> int:
    session = _get_session()
    try:
        result = session.execute(
            select(func.count(func.distinct(Detection.tracking_id))).where(
                Detection.counted_status == True
            )
        ).scalar()
        return result or 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Query operations — invalid QR logs
# ---------------------------------------------------------------------------


def get_invalid_qr_logs(
    limit: int = 100,
    offset: int = 0,
    error_type_filter: Optional[str] = None,
) -> list[InvalidQrLog]:
    session = _get_session()
    try:
        stmt = (
            select(InvalidQrLog)
            .order_by(InvalidQrLog.timestamp.desc())
        )
        if error_type_filter is not None and error_type_filter in _VALID_ERROR_TYPES:
            stmt = stmt.where(InvalidQrLog.error_type == error_type_filter)
        stmt = stmt.limit(limit).offset(offset)
        return list(session.execute(stmt).scalars().all())
    finally:
        session.close()


def get_total_invalid_qr_count() -> int:
    session = _get_session()
    try:
        result = session.execute(
            select(func.count(InvalidQrLog.id))
        ).scalar()
        return result or 0
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Query operations — duplicate events
# ---------------------------------------------------------------------------


def get_duplicate_events(
    limit: int = 100,
    offset: int = 0,
) -> list[DuplicateEvent]:
    session = _get_session()
    try:
        stmt = (
            select(DuplicateEvent)
            .order_by(DuplicateEvent.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(session.execute(stmt).scalars().all())
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Unified event feed
# ---------------------------------------------------------------------------


def get_all_events(
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    session = _get_session()
    try:
        dets = list(
            session.execute(
                select(Detection)
                .order_by(Detection.timestamp.desc())
                .limit(limit)
                .offset(offset)
            ).scalars().all()
        )
        invalids = list(
            session.execute(
                select(InvalidQrLog)
                .order_by(InvalidQrLog.timestamp.desc())
                .limit(limit)
                .offset(offset)
            ).scalars().all()
        )
        dups = list(
            session.execute(
                select(DuplicateEvent)
                .order_by(DuplicateEvent.timestamp.desc())
                .limit(limit)
                .offset(offset)
            ).scalars().all()
        )

        events: list[dict] = []

        for d in dets:
            events.append({**d.to_dict(), "event_type": "detection"})

        for i in invalids:
            events.append({
                "id": i.id,
                "tracking_id": i.tracking_id,
                "error_type": i.error_type,
                "timestamp": i.timestamp.isoformat() if i.timestamp else None,
                "camera_id": i.camera_id,
                "box_x": i.box_x,
                "box_y": i.box_y,
                "box_width": i.box_width,
                "box_height": i.box_height,
                "event_type": "invalid_qr",
            })

        for d in dups:
            events.append({
                "id": d.id,
                "tracking_id": d.tracking_id,
                "qr_data": d.qr_data,
                "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                "camera_id": d.camera_id,
                "box_x": d.box_x,
                "box_y": d.box_y,
                "box_width": d.box_width,
                "box_height": d.box_height,
                "event_type": "duplicate",
            })

        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
        return events[:limit]

    finally:
        session.close()
