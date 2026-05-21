"""TikTok-shaped exceptions + handler for TikTok routes.

Handlers ``raise AccessTokenInvalidError()`` (etc.); FastAPI's exception
dispatcher routes the instance to :func:`tiktok_exception_handler` via the
``TikTokAPIError`` base — ``isinstance`` dispatch picks up every subclass.

Each concrete subclass freezes the wire-shape constants (``status_code``,
``code``) as class attributes, and supplies a ``default_message``. Pass a
per-call message to the constructor to override (e.g.
``InvalidParamError(f"Unknown publish_id {pid!r}")``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from posthole.routes.platforms.tiktok.responses import tiktok_error

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse


class TikTokAPIError(Exception):
    """Base for every TikTok-shaped error. Rendered by :func:`tiktok_exception_handler`."""

    status_code: ClassVar[int] = 400
    code: ClassVar[str] = "internal_error"
    default_message: ClassVar[str] = "Bad request"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)

    def to_response(self) -> JSONResponse:
        """Serialize to a TikTok dual-envelope JSONResponse."""
        return tiktok_error(
            http_status=self.status_code,
            code=self.code,
            message=self.message,
        )


class InvalidParamError(TikTokAPIError):
    """Generic 400 for malformed params, missing fields, wrong enum values, etc."""

    status_code = 400
    code = "invalid_param"
    default_message = "Invalid request parameter"


class InvalidRedirectUriError(TikTokAPIError):
    """``redirect_uri`` is missing or non-http(s)."""

    status_code = 400
    code = "invalid_param"
    default_message = "redirect_uri must be an http(s) URL"


class UnknownAccountIdError(TikTokAPIError):
    """``account_id`` does not match any seeded TikTok account."""

    status_code = 400
    code = "invalid_param"
    default_message = "Unknown account_id"


class InvalidGrantError(TikTokAPIError):
    """OAuth code/refresh_token is missing, unknown, wrong-kind, or grant_type unsupported."""

    status_code = 400
    code = "invalid_grant"
    default_message = "Invalid grant"


class AccessTokenInvalidError(TikTokAPIError):
    """Bearer token is unknown or refers to a non-TikTok account."""

    status_code = 401
    code = "access_token_invalid"
    default_message = "Invalid access token"


class MissingBearerHeaderError(TikTokAPIError):
    """No ``Authorization: Bearer ...`` header on a bearer-protected endpoint."""

    status_code = 401
    code = "access_token_invalid"
    default_message = "Missing or malformed Authorization header"


class UserNotFoundError(TikTokAPIError):
    """Token resolved but the account it belongs to is missing / not a TikTok one."""

    status_code = 404
    code = "user_not_found"
    default_message = "Account not found"


class PublishNotFoundError(TikTokAPIError):
    """Unknown ``publish_id`` on chunked upload / status fetch — 404, ``invalid_param``."""

    status_code = 404
    code = "invalid_param"
    default_message = "Unknown publish_id"


async def tiktok_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI handler — converts any :class:`TikTokAPIError` into its wire envelope."""
    if not isinstance(exc, TikTokAPIError):  # pragma: no cover — defensive
        raise exc
    return exc.to_response()
