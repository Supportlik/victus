"""Application-level errors. The API maps them to RFC 9457 problem details."""

from __future__ import annotations

from typing import Any


class ApplicationError(Exception):
    """Base class; ``status`` is the HTTP status the API layer uses."""

    status = 400
    title = "Bad request"

    def __init__(self, detail: str = "", *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.errors = errors or []


class NotFound(ApplicationError):
    status = 404
    title = "Not found"


class Conflict(ApplicationError):
    status = 409
    title = "Conflict"


class ValidationFailed(ApplicationError):
    status = 422
    title = "Validation failed"


class Forbidden(ApplicationError):
    status = 403
    title = "Forbidden"


class Unauthenticated(ApplicationError):
    status = 401
    title = "Authentication required"


class LockHeldByOtherRun(Conflict):
    title = "Day locked by another run"


class NotImplementedYet(ApplicationError):
    status = 501
    title = "Not implemented"
