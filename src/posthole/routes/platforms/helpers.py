"""Cross-platform helpers used by per-platform code."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def query_param(url: str, key: str) -> str:
    """Return the first value for ``key`` in ``url``'s query string."""
    values = parse_qs(urlparse(url).query).get(key, [])

    if not values:
        msg = f"redirect URL missing ?{key}= in {url!r}"
        raise RuntimeError(msg)

    return values[0]


def is_safe_redirect_uri(uri: str) -> bool:
    """Return whether ``uri`` is an HTTP(S) URL safe to redirect to.

    Refuses non-http(s) schemes (rejects ``javascript:`` payloads) and URIs
    with no parseable hostname. No host allowlist — real social APIs (Meta,
    TikTok) exact-match against URIs registered in the developer portal
    rather than restricting by host shape, so posthole accepts any HTTP(S)
    host. Operators relying on registration semantics drive that through
    seed data instead.
    """
    try:
        parts = urlparse(uri)
    except ValueError:
        return False

    if parts.scheme not in {"http", "https"}:
        return False

    return bool(parts.hostname)
