import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

LOGGER = logging.getLogger("api.exceptions")


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
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
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"{msg}: {field}",
            },
        },
    )


async def general_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal error occurred",
            },
        },
    )
