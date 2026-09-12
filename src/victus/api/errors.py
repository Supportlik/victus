"""RFC 9457 problem details for every error the API emits."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from victus.application.errors import ApplicationError
from victus.application.tenant_context import ScopeError

PROBLEM = "application/problem+json"

_TITLES = {
    400: "Bad request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Payload too large",
    415: "Unsupported media type",
    422: "Validation failed",
    429: "Too many requests",
    500: "Internal server error",
    501: "Not implemented",
    503: "Service unavailable",
}


def problem(
    status: int,
    detail: str | None = None,
    *,
    title: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    type_: str = "about:blank",
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title or _TITLES.get(status, "Error"),
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def _app_error(_: Request, exc: ApplicationError) -> JSONResponse:
        return problem(exc.status, exc.detail, title=exc.title, errors=exc.errors or None)

    @app.exception_handler(ScopeError)
    async def _scope_error(_: Request, exc: ScopeError) -> JSONResponse:
        return problem(403, str(exc))

    @app.exception_handler(PermissionError)
    async def _permission_error(_: Request, exc: PermissionError) -> JSONResponse:
        # Repositories raise PermissionError for foreign-tenant access: never leak existence.
        return problem(404, "not found")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "field": ".".join(
                    str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")
                ),
                "message": str(e.get("msg", "invalid")),
            }
            for e in exc.errors()
        ]
        return problem(422, "request body or parameters are invalid", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else None
        return problem(exc.status_code, detail, headers=dict(exc.headers or {}))
