import logging
import os
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from app.api.v1 import v1_router
from app.core.config import SETTINGS
from app.core.exceptions import (
    AppError,
    app_error_handler,
    general_exception_handler,
    validation_exception_handler,
)
from app.database.base import Base
from app.database.session import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

LOGGER = logging.getLogger("app.main")

_CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app = FastAPI(
    title=SETTINGS.app_name,
    version=SETTINGS.app_version,
    docs_url="/docs" if SETTINGS.debug else None,
    redoc_url="/redoc" if SETTINGS.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, general_exception_handler)

app.include_router(v1_router)


@app.on_event("startup")
async def _startup() -> None:
    from sqlalchemy import text

    # Ensure SUPER_ADMIN exists in PostgreSQL enum type outside transaction block
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit_engine.connect() as conn:
        try:
            await conn.execute(
                text("ALTER TYPE user_role_enum ADD VALUE 'SUPER_ADMIN'")
            )
            LOGGER.info("Successfully added SUPER_ADMIN to user_role_enum")
        except Exception as e:
            LOGGER.debug("Could not alter user_role_enum (already present or not pg): %s", e)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    LOGGER.info("Database tables created / verified")

    from app.database.session import async_session_factory
    from app.auth.seed import seed_super_admin

    async with async_session_factory() as session:
        await seed_super_admin(session)
        await session.commit()
    LOGGER.info("Seed complete")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await engine.dispose()
    LOGGER.info("Engine disposed")


@app.get("/health", summary="Health check")
async def health() -> dict:
    return {
        "success": True,
        "data": {"status": "running", "version": SETTINGS.app_version},
        "error": None,
    }


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=SETTINGS.host,
        port=SETTINGS.port,
        reload=SETTINGS.debug,
    )


if __name__ == "__main__":
    main()
