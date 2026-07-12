import logging
import time
import uuid

import jwt
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)


def _get_user_id_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
    user_id_str = payload.get("sub")
    if not user_id_str:
        return None
    try:
        return str(uuid.UUID(user_id_str))
    except ValueError:
        return None


def _get_request_context(request: Request) -> dict:
    request_id = request.scope.get("request_id")
    if request_id is None:
        request_id = str(uuid.uuid4())
    start_time = request.scope.get("start_time")
    duration = None
    if start_time is not None:
        duration = round(time.monotonic() - start_time, 4)
    user_id = _get_user_id_from_request(request)
    return {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "user_id": user_id,
        "duration": duration,
    }


def _log_error(ctx: dict, status_code: int, detail: str, exc_info: bool = False) -> None:
    log_data = {
        "request_id": ctx["request_id"],
        "method": ctx["method"],
        "path": ctx["path"],
        "status_code": status_code,
        "user_id": ctx["user_id"],
        "duration": ctx["duration"],
        "detail": detail,
    }
    if exc_info:
        logger.exception("Request failed", extra=log_data)
    else:
        logger.error("Request failed", extra=log_data)


def _build_response(ctx: dict, status_code: int, detail: str, extra: dict | None = None) -> JSONResponse:
    body = {"detail": detail, "request_id": ctx["request_id"]}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    ctx = _get_request_context(request)
    _log_error(ctx, exc.status_code, exc.detail)
    return _build_response(ctx, exc.status_code, exc.detail)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    ctx = _get_request_context(request)
    errors = [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]
    _log_error(ctx, 422, "Validation error")
    return _build_response(ctx, 422, "Validation error", extra={"errors": errors})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    ctx = _get_request_context(request)
    _log_error(ctx, 500, str(exc), exc_info=True)
    if settings.DEBUG:
        detail = str(exc)
    else:
        detail = "Internal server error"
    return _build_response(ctx, 500, detail)
