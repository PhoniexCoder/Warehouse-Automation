import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

LOGGER = logging.getLogger("app.core.exceptions")


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(AppError):
    def __init__(self, entity: str, identifier: str | int) -> None:
        super().__init__(
            code="NOT_FOUND",
            message=f"{entity} not found: {identifier}",
            status_code=404,
        )


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(code="CONFLICT", message=message, status_code=409)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(code="UNAUTHORIZED", message=message, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(code="FORBIDDEN", message=message, status_code=403)


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": exc.code, "message": exc.message},
        },
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = " -> ".join(str(p) for p in first.get("loc", [])) if first.get("loc") else "unknown"
    msg = first.get("msg", "Validation error") if first else "Validation error"
    LOGGER.warning("Validation error: %s (%s)", msg, field)
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "data": None,
            "error": {"code": "VALIDATION_ERROR", "message": f"{msg}: {field}"},
        },
    )


async def general_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred"},
        },
    )
