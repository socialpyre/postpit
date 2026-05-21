"""Meta-shaped exceptions + handler for Instagram routes.

Handlers ``raise InvalidAccessTokenError()`` (etc.); FastAPI's exception
dispatcher routes the instance to :func:`meta_exception_handler` via the
``MetaAPIError`` base — ``isinstance`` dispatch picks up every subclass.

Each concrete subclass freezes the wire-shape constants (``status_code``,
``error_type``, ``code``, optional ``error_subcode``) as class attributes,
and supplies a ``default_message``. Pass a per-call message to the
constructor to override (e.g. ``UnknownAccountIdError(f"Unknown account_id
{account_id!r}")``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from posthole.routes.platforms.instagram.responses import meta_error

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse


class MetaAPIError(Exception):
    """Base for every Meta-shaped error. Rendered by :func:`meta_exception_handler`."""

    status_code: ClassVar[int] = 400
    error_type: ClassVar[str] = "GraphMethodException"
    code: ClassVar[int] = 0
    error_subcode: ClassVar[int | None] = None
    default_message: ClassVar[str] = "Bad request"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)

    def to_response(self) -> JSONResponse:
        """Serialize to a Meta-shaped JSONResponse."""
        return meta_error(
            status=self.status_code,
            message=self.message,
            error_type=self.error_type,
            code=self.code,
            error_subcode=self.error_subcode,
        )


class InvalidAccessTokenError(MetaAPIError):
    """Token presented to an OAuth endpoint (``/me``, ``/access_token``) is unknown.

    Meta returns 400 here — the request shape is fine, the token just doesn't
    resolve. For endpoints that gate on auth (publishing), raise
    :class:`UnauthorizedError` instead (401).
    """

    status_code = 400
    error_type = "OAuthException"
    code = 190
    default_message = "Invalid access token"


class UnauthorizedError(MetaAPIError):
    """Auth-gated endpoint received no/invalid token. Publishing's auth gate raises this."""

    status_code = 401
    error_type = "OAuthException"
    code = 190
    default_message = "Invalid OAuth access token"


class InvalidLongLivedTokenError(MetaAPIError):
    """Token presented to ``/refresh_access_token`` is missing or not long-lived."""

    status_code = 400
    error_type = "OAuthException"
    code = 190
    default_message = "Invalid long-lived access token"


class InvalidAuthCodeError(MetaAPIError):
    """OAuth code is unknown or already consumed."""

    status_code = 400
    error_type = "OAuthException"
    code = 100
    error_subcode = 2207001
    default_message = "Invalid authorization code"


class UnknownAccountIdError(MetaAPIError):
    """``account_id`` does not match any seeded IG account."""

    status_code = 400
    code = 100
    default_message = "Unknown account_id"


class AccountNotFoundError(MetaAPIError):
    """Token resolved but the account it belongs to is missing."""

    status_code = 404
    code = 803
    default_message = "Account not found"


class InvalidRedirectUriError(MetaAPIError):
    """``redirect_uri`` is missing or non-http(s)."""

    status_code = 400
    error_type = "OAuthException"
    code = 100
    default_message = "redirect_uri must be an http(s) URL"


class UnsupportedMediaTypeError(MetaAPIError):
    """``media_type=`` other than IMAGE — phase 1 limitation."""

    status_code = 400
    code = 100
    default_message = "Unsupported media_type"


class MissingImageUrlError(MetaAPIError):
    """``image_url=`` was empty on a container create."""

    status_code = 400
    code = 100
    error_subcode = 2207001
    default_message = "image_url is required for IMAGE containers"


class ContainerNotFoundError(MetaAPIError):
    """No container/post matches the given ``container_id``/``creation_id``."""

    status_code = 404
    code = 100
    default_message = "Container not found"


async def meta_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI handler — converts any :class:`MetaAPIError` into its wire envelope.

    FastAPI's ``add_exception_handler`` is typed as ``Callable[[Request,
    Exception], ...]``. We register this for :class:`MetaAPIError` so
    isinstance-narrowing inside the body is safe.
    """
    if not isinstance(exc, MetaAPIError):  # pragma: no cover — defensive
        raise exc
    return exc.to_response()
