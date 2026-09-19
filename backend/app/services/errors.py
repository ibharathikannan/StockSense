"""Domain errors raised by services.

Services hold business rules and know nothing about HTTP. They raise these
instead of ``HTTPException``; one handler in ``app/main.py`` turns them into
JSON responses with the matching status code, in FastAPI's usual
``{"detail": "..."}`` shape.
"""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class BadRequest(ServiceError):
    status_code = 400


class Forbidden(ServiceError):
    status_code = 403


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409
