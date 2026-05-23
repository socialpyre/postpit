"""SQL for the ``posts`` table — read by :mod:`posthole.db.posts`."""

from __future__ import annotations

# Carousel children are upload stubs in IG's two-step API, not posts in
# their own right — exclude them from inbox-facing list/count queries so
# one published carousel renders as one row, not 1+N. Internal lookups
# (get_by_external_ref, list_by_external_refs) still see children.
COUNT_ALL = "SELECT COUNT(*) AS n FROM posts WHERE is_carousel_item = 0"

COUNT_BY_STATUS = (
    "SELECT status, COUNT(*) AS n FROM posts WHERE is_carousel_item = 0 GROUP BY status"
)

GET_BY_EXTERNAL_REF = "SELECT * FROM posts WHERE external_ref = ?"

GET_BY_ID = "SELECT * FROM posts WHERE id = ?"

INSERT = (
    "INSERT INTO posts ("
    "id, platform, account_id, caption, status, created_at, "
    "external_ref, media_url, media_type, media_items, "
    "container_status, poll_count, poll_threshold, "
    "inject_next_failure_kind, is_carousel_item, child_container_ids"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

LIST_RECENT = (
    "SELECT posts.* FROM posts "
    # LEFT JOIN so posts without a matching accounts row still appear when
    # the user isn't searching. The username is consulted only by the
    # :like_q branch below.
    "LEFT JOIN accounts ON accounts.id = posts.account_id "
    "WHERE posts.is_carousel_item = 0 "
    "AND (:platform IS NULL OR posts.platform = :platform) "
    "AND (:status IS NULL OR posts.status = :status) "
    # :like_q is the wrapped ``%needle%`` form produced by
    # ``posthole.db.query.like_needle`` — it pre-escapes ``%`` / ``_`` /
    # ``\`` so the ESCAPE '\' clause makes literal wildcards behave.
    # NULL short-circuits the LIKE branch when search is inactive.
    "AND (:like_q IS NULL OR "
    "     posts.caption LIKE :like_q ESCAPE '\\' "
    "  OR posts.account_id LIKE :like_q ESCAPE '\\' "
    "  OR accounts.username LIKE :like_q ESCAPE '\\') "
    "ORDER BY posts.created_at DESC LIMIT :limit"
)

MARK_FAILED = "UPDATE posts SET status = 'failed', failure_reason = ? WHERE id = ?"

MARK_PUBLISHED = "UPDATE posts SET status = 'published', published_at = ? WHERE id = ?"

MARK_PUBLISHED_BY_EXTERNAL_REF = (
    "UPDATE posts SET status = 'published', published_at = ?, platform_post_id = ? "
    "WHERE external_ref = ?"
)

# Container-state extensions (migration 0005).

INCREMENT_POLL_COUNT = "UPDATE posts SET poll_count = poll_count + 1 WHERE external_ref = ?"

SET_CONTAINER_STATUS_BY_EXTERNAL_REF = (
    "UPDATE posts SET container_status = ? WHERE external_ref = ?"
)

SET_INJECT_FAILURE_BY_EXTERNAL_REF = (
    "UPDATE posts SET inject_next_failure_kind = ? WHERE external_ref = ?"
)

CLEAR_INJECT_FAILURE_BY_EXTERNAL_REF = (
    "UPDATE posts SET inject_next_failure_kind = NULL WHERE external_ref = ?"
)

LIST_BY_EXTERNAL_REFS = (
    # NB: caller is responsible for the placeholder expansion — we don't know
    # the cardinality up front. See ``posts.list_by_external_refs``.
    "SELECT * FROM posts WHERE external_ref IN ({placeholders})"
)
