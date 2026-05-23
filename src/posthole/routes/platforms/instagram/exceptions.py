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


class RateLimitedError(MetaAPIError):
    """Generic rate-limit exception — concrete subclasses pin the Meta error code.

    Meta returns four distinct ``code`` values for "you're being throttled"
    (4/17/32/613) depending on which limit tripped. Real clients commonly
    branch on the numeric code rather than the message, so the mock
    exposes each as its own subclass.
    """

    status_code = 400
    error_type = "OAuthException"
    default_message = "Rate limited"


class ApplicationRateLimitedError(RateLimitedError):
    """``code=4`` — the app-level call quota tripped."""

    code = 4
    default_message = "Application request limit reached"


class UserRateLimitedError(RateLimitedError):
    """``code=17`` — the per-user call quota tripped."""

    code = 17
    default_message = "User request limit reached"


class PageRateLimitedError(RateLimitedError):
    """``code=32`` — the per-page call quota tripped."""

    code = 32
    default_message = "Page request limit reached"


class GenericRateLimitedError(RateLimitedError):
    """``code=613`` — the generic "calls to this api have exceeded the rate limit"."""

    code = 613
    default_message = "Calls to this api have exceeded the rate limit"


class MediaUnreachableError(MetaAPIError):
    """``code=100, error_subcode=2207026`` — IG could not fetch the media URL."""

    status_code = 400
    code = 100
    error_subcode = 2207026
    default_message = "Media not reachable"


class MediaFormatUnsupportedError(MediaUnreachableError):
    """``code=100, error_subcode=9004`` — IG fetched the media but can't decode it.

    Subclasses :class:`MediaUnreachableError` so callers catching the
    "we couldn't get usable media" failure mode hit both via one ``except``.
    """

    error_subcode = 9004
    default_message = "Media format unsupported"


class PasswordChangedError(MetaAPIError):
    """``code=190, error_subcode=460`` — token invalidated because password changed."""

    status_code = 400
    error_type = "OAuthException"
    code = 190
    error_subcode = 460
    default_message = "The user changed their password"


class TokenExpiredError(MetaAPIError):
    """``code=190, error_subcode=463`` — token aged out of its TTL."""

    status_code = 400
    error_type = "OAuthException"
    code = 190
    error_subcode = 463
    default_message = "Access token has expired"


class TokenRevokedError(MetaAPIError):
    """``code=190, error_subcode=467`` — user revoked the app's permissions."""

    status_code = 400
    error_type = "OAuthException"
    code = 190
    error_subcode = 467
    default_message = "Access token has been revoked"


class CarouselChildPublishError(MetaAPIError):
    """``code=100, error_subcode=2207020`` — direct publish of a child container.

    Child containers (``is_carousel_item=true``) can only be published as
    part of a parent CAROUSEL container. Real Meta returns this when a
    client passes a child's id to ``/{user_id}/media_publish``.
    """

    status_code = 400
    code = 100
    error_subcode = 2207020
    default_message = "Carousel child containers cannot be published directly"


class CarouselChildInvalidError(MetaAPIError):
    """A referenced ``children=`` id is missing or not flagged as a carousel item."""

    status_code = 400
    code = 100
    default_message = "Invalid carousel child container"


class ContainerExpiredError(MetaAPIError):
    """``code=9007, error_subcode=2207027`` — container is past its useful TTL.

    IG containers are short-lived; once a container hits EXPIRED status,
    /media_publish refuses to use it. The mock surfaces the same shape
    so retry/cleanup logic in clients can be exercised.
    """

    status_code = 400
    code = 9007
    error_subcode = 2207027
    default_message = "Media container has expired"


class ContainerNotReadyError(MetaAPIError):
    """``status_code != FINISHED`` at publish time — same wire shape as expired."""

    status_code = 400
    code = 9007
    error_subcode = 2207027
    default_message = "Media container is not ready to publish"


async def meta_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI handler — converts any :class:`MetaAPIError` into its wire envelope.

    FastAPI's ``add_exception_handler`` is typed as ``Callable[[Request,
    Exception], ...]``. We register this for :class:`MetaAPIError` so
    isinstance-narrowing inside the body is safe.
    """
    if not isinstance(exc, MetaAPIError):  # pragma: no cover — defensive
        raise exc
    return exc.to_response()
