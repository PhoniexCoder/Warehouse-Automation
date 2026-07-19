from datetime import datetime, timedelta, timezone
import logging

import jwt

from app.core.config import SETTINGS

LOGGER = logging.getLogger(__name__)

ACCESS_TOKEN_KEY = "access"
REFRESH_TOKEN_KEY = "refresh"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(subject: str, role: str) -> str:
    expires = _now() + timedelta(minutes=SETTINGS.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "type": ACCESS_TOKEN_KEY,
        "iat": _now(),
        "exp": expires,
    }
    token = jwt.encode(
        payload, SETTINGS.jwt_secret, algorithm=SETTINGS.jwt_algorithm,
    )
    return token


IMPERSONATION_TOKEN_KEY = "impersonation"


def create_impersonation_token(
    subject: str,
    role: str,
    impersonator_id: str,
    expires_minutes: int = 30,
) -> str:
    expires = _now() + timedelta(minutes=expires_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "impersonator_id": impersonator_id,
        "type": IMPERSONATION_TOKEN_KEY,
        "iat": _now(),
        "exp": expires,
    }
    token = jwt.encode(
        payload, SETTINGS.jwt_secret, algorithm=SETTINGS.jwt_algorithm,
    )
    return token


def create_refresh_token(subject: str) -> str:
    expires = _now() + timedelta(days=SETTINGS.refresh_token_expire_days)
    payload = {
        "sub": subject,
        "type": REFRESH_TOKEN_KEY,
        "iat": _now(),
        "exp": expires,
    }
    token = jwt.encode(
        payload, SETTINGS.jwt_secret, algorithm=SETTINGS.jwt_algorithm,
    )
    return token


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, SETTINGS.jwt_secret, algorithms=[SETTINGS.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        LOGGER.warning("Token expired")
        raise
    except jwt.InvalidTokenError as exc:
        LOGGER.warning("Invalid token: %s", exc)
        raise
