import os
import sys
from dataclasses import dataclass, field


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        sys.exit(f"FATAL: {name} environment variable is not set. Refusing to start.")
    return val


@dataclass(frozen=True)
class Settings:
    app_name: str = "Vistock Business Backend"
    app_version: str = "1.0.0"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    database_url: str = field(default_factory=lambda: _require_env("DATABASE_URL"))
    database_echo: bool = os.getenv("DATABASE_ECHO", "false").lower() == "true"
    database_pool_size: int = int(os.getenv("DATABASE_POOL_SIZE", "10"))
    database_max_overflow: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "20"))

    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8001"))

    ai_engine_url: str = os.getenv("AI_ENGINE_URL", "http://localhost:8000")
    internal_api_key: str = field(default_factory=lambda: _require_env("INTERNAL_API_KEY"))

    jwt_secret: str = field(default_factory=lambda: _require_env("JWT_SECRET"))
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )
    refresh_token_expire_days: int = int(
        os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
    )


SETTINGS = Settings()
