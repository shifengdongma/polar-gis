import json
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def error_payload(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "requestId": getattr(request.state, "request_id", None),
        "details": details,
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, exc.code, exc.message, exc.details),
    )


def _serializable_validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Pydantic may put non-JSON-serializable values (e.g. ValueError) in ctx."""
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        item = {key: value for key, value in error.items() if key not in {"ctx", "input"}}
        context = error.get("ctx")
        if context:
            item["ctx"] = {key: str(value) for key, value in context.items()}
        supplied = error.get("input")
        try:
            json.dumps(supplied)
            item["input"] = supplied
        except (TypeError, ValueError):
            item["input"] = str(supplied)
        details.append(item)
    return details


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            request, "VALIDATION_ERROR", "请求参数校验失败", _serializable_validation_details(exc)
        ),
    )

