"""Failure injection for Instagram routes — caption sentinel + header parsing."""

from __future__ import annotations

import re
from typing import Literal

from posthole.routes.platforms.instagram.exceptions import (
    ContainerExpiredError,
    MediaUnreachableError,
    MetaAPIError,
    TokenRevokedError,
    UserRateLimitedError,
)

InjectionKind = Literal[
    "rate_limited",
    "media_unreachable",
    "auth_revoked",
    "expired",
    "publish_error",
]

INJECTION_KINDS: frozenset[str] = frozenset(
    {"rate_limited", "media_unreachable", "auth_revoked", "expired", "publish_error"},
)

# ``[posthole:fail=<kind>]`` — match the longest contiguous kind token after
# the literal prefix. Tolerant of surrounding whitespace; greedy on the
# kind so values with underscores (``media_unreachable``) survive intact.
_SENTINEL_RE = re.compile(r"\s*\[posthole:fail=([a-z_]+)\]\s*")


def extract_caption_sentinel(caption: str | None) -> tuple[str | None, str | None]:
    """Pull the first ``[posthole:fail=<kind>]`` sentinel out of ``caption``.

    Returns ``(caption_without_sentinel, kind)``. Both fields are ``None``
    when the caption was empty; the kind is ``None`` when the caption has
    no recognized sentinel. The sentinel is removed even if the kind is
    unrecognized — the caller decides whether unknown kinds become errors
    or no-ops.
    """
    if not caption:
        return caption, None
    match = _SENTINEL_RE.search(caption)
    if match is None:
        return caption, None
    kind = match.group(1)
    cleaned = _SENTINEL_RE.sub(" ", caption, count=1).strip() or None
    if kind not in INJECTION_KINDS:
        return cleaned, None
    return cleaned, kind


def header_injection_kind(header_value: str | None) -> str | None:
    """Parse the ``X-Posthole-Inject-Failure`` header value to a recognized kind."""
    if not header_value:
        return None
    value = header_value.strip().lower()
    return value if value in INJECTION_KINDS else None


def raise_for_kind(kind: str) -> None:
    """Raise the :class:`MetaAPIError` subclass that matches ``kind``.

    Unknown kinds raise a generic :class:`MetaAPIError` — by the time a
    kind reaches this function it should have been validated against
    :data:`INJECTION_KINDS`, so unknown values mean a programming error.
    """
    if kind == "rate_limited":
        raise UserRateLimitedError
    if kind == "media_unreachable":
        raise MediaUnreachableError
    if kind == "auth_revoked":
        raise TokenRevokedError
    if kind == "expired":
        raise ContainerExpiredError
    if kind == "publish_error":
        msg = "Injected publish error"
        raise MetaAPIError(msg)
    msg = f"Unknown injection kind: {kind!r}"
    raise MetaAPIError(msg)
