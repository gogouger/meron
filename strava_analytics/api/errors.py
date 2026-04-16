"""Standard error envelope + handlers.

Every non-2xx response from the API has exactly the shape::

    {"error": {"code": "...", "message": "...", "details": {...}}}

Mobile clients can write a single deserializer for the whole surface.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Raise this to emit a structured error response."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, code: str | None = None,
                 status_code: int | None = None,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class NotFound(ApiError):
    status_code = 404
    code = "not_found"


class Unauthorized(ApiError):
    status_code = 401
    code = "unauthorized"


class ValidationError(ApiError):
    status_code = 400
    code = "validation_error"


class Conflict(ApiError):
    status_code = 409
    code = "conflict"


def envelope(code: str, message: str,
             details: dict[str, Any] | None = None) -> dict:
    """Return a standard error dict."""
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def register_error_handlers(app: Flask) -> None:
    """Convert all exceptions thrown from handlers into the error envelope."""

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return jsonify(envelope(err.code, err.message, err.details)), err.status_code

    # pydantic import is optional here — validation errors are only raised
    # once the schemas module is in play, but registering the handler early
    # means no matter when pydantic is imported the handler is ready.
    try:
        from pydantic import ValidationError as PydanticValidationError

        @app.errorhandler(PydanticValidationError)
        def _handle_pydantic(err: PydanticValidationError):
            return jsonify(envelope(
                "validation_error",
                "Request body failed validation.",
                {"errors": err.errors()},
            )), 400
    except ImportError:
        pass

    @app.errorhandler(HTTPException)
    def _handle_http(err: HTTPException):
        code = (err.name or "http_error").lower().replace(" ", "_")
        return jsonify(envelope(code, err.description or err.name)), err.code or 500

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        logger.exception("Unhandled API exception")
        return jsonify(envelope(
            "internal_error",
            "Something went wrong on the server.",
        )), 500
