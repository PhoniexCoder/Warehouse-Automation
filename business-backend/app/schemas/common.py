from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    success: bool = True
    data: object | None = None
    error: ErrorDetail | None = None
