import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    app_name: str = "Warehouse Business Backend"
    app_version: str = "1.0.0"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse",
        )
    )
    database_echo: bool = os.getenv("DATABASE_ECHO", "false").lower() == "true"
    database_pool_size: int = int(os.getenv("DATABASE_POOL_SIZE", "10"))
    database_max_overflow: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "20"))

    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8001"))

    ai_engine_url: str = os.getenv("AI_ENGINE_URL", "http://localhost:8000")

    jwt_secret: str = os.getenv("JWT_SECRET", "super-secret-key-change-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )
    refresh_token_expire_days: int = int(
        os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
    )


SETTINGS = Settings()
