"""Posts: the central mock-server entity — one publish attempt against a platform."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from posthole.db.query import like_needle
from posthole.db.sql import posts as sql

if TYPE_CHECKING:
    import sqlite3

    from posthole.db.database import Database


MediaItemKind = Literal["IMAGE", "VIDEO"]
MediaType = Literal["IMAGE", "VIDEO", "CAROUSEL"]
PostStatus = Literal["pending", "published", "failed"]
ContainerStatus = Literal["IN_PROGRESS", "FINISHED", "ERROR", "EXPIRED"]


@dataclass(slots=True, frozen=True)
class Media:
    """One item in a post's media set (carousel slide or singleton).

    ``kind`` is :data:`MediaItemKind` (IMAGE | VIDEO), not :data:`MediaType` —
    CAROUSEL describes a *parent* container, never an individual slide.
    """

    ordinal: int
    kind: MediaItemKind
    url: str


@dataclass(slots=True)
class Post:
    """One publish attempt against a platform — the central mock-server entity.

    ``external_ref`` is the opaque identifier the platform mints for the
    pending publish (IG's container_id, TikTok's publish_id).
    ``platform_post_id`` is the final platform-side identifier returned
    once the publish completes.

    ``media`` is the ordered list of media items. For single-media posts
    it's a 1-item list synthesized from ``media_url`` / ``media_type`` if
    the row pre-dates carousel support; for carousel posts it's hydrated
    from the ``media_items`` JSON column.
    """

    id: str
    platform: str
    account_id: str
    caption: str | None
    status: PostStatus
    created_at: datetime
    published_at: datetime | None
    failure_reason: str | None
    external_ref: str | None
    media_url: str | None
    media_type: MediaType | None
    platform_post_id: str | None
    media: list[Media] = field(default_factory=list)
    container_status: ContainerStatus = "IN_PROGRESS"
    poll_count: int = 0
    poll_threshold: int = 0
    inject_next_failure_kind: str | None = None
    is_carousel_item: bool = False
    child_container_ids: list[str] = field(default_factory=list)


def create(
    db: Database,
    *,
    platform: str,
    account_id: str,
    caption: str | None = None,
    external_ref: str | None = None,
    media_url: str | None = None,
    media_type: MediaType | None = None,
    media: list[Media] | None = None,
    container_status: ContainerStatus = "IN_PROGRESS",
    poll_threshold: int = 0,
    inject_next_failure_kind: str | None = None,
    is_carousel_item: bool = False,
    child_container_ids: list[str] | None = None,
) -> Post:
    """Insert a new post in ``pending`` status; return the hydrated row."""
    media_list = list(media) if media else []
    media_items_json = (
        json.dumps([{"ordinal": m.ordinal, "kind": m.kind, "url": m.url} for m in media_list])
        if media_list
        else None
    )
    if not media_list and media_url:
        # CAROUSEL describes a parent and never has its own media_url, so the
        # synthesized item is always IMAGE | VIDEO — narrow back to MediaItemKind.
        item_kind: MediaItemKind = "VIDEO" if media_type == "VIDEO" else "IMAGE"
        media_list = [Media(ordinal=0, kind=item_kind, url=media_url)]

    children = list(child_container_ids) if child_container_ids else []
    child_csv = ",".join(children) if children else None

    post = Post(
        id=str(uuid.uuid4()),
        platform=platform,
        account_id=account_id,
        caption=caption,
        status="pending",
        created_at=datetime.now(UTC),
        published_at=None,
        failure_reason=None,
        external_ref=external_ref,
        media_url=media_url,
        media_type=media_type,
        platform_post_id=None,
        media=media_list,
        container_status=container_status,
        poll_count=0,
        poll_threshold=poll_threshold,
        inject_next_failure_kind=inject_next_failure_kind,
        is_carousel_item=is_carousel_item,
        child_container_ids=children,
    )

    with db.cursor() as cur:
        cur.execute(
            sql.INSERT,
            (
                post.id,
                post.platform,
                post.account_id,
                post.caption,
                post.status,
                _iso(post.created_at),
                post.external_ref,
                post.media_url,
                post.media_type,
                media_items_json,
                post.container_status,
                post.poll_count,
                post.poll_threshold,
                post.inject_next_failure_kind,
                1 if post.is_carousel_item else 0,
                child_csv,
            ),
        )

    return post


def clear_inject_failure_by_external_ref(db: Database, external_ref: str) -> None:
    """Clear an armed failure injection — call after the failure has been raised."""
    with db.cursor() as cur:
        cur.execute(sql.CLEAR_INJECT_FAILURE_BY_EXTERNAL_REF, (external_ref,))


def count(db: Database) -> int:
    """Return the total number of posts."""
    with db.cursor() as cur:
        cur.execute(sql.COUNT_ALL)
        row = cur.fetchone()
    return int(row["n"]) if row else 0


def count_by_status(db: Database) -> dict[PostStatus, int]:
    """Return per-status post counts (statuses with zero rows are absent)."""
    with db.cursor() as cur:
        cur.execute(sql.COUNT_BY_STATUS)
        rows = cur.fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def get(db: Database, post_id: str) -> Post | None:
    """Return the post with this id, or ``None``."""
    with db.cursor() as cur:
        cur.execute(sql.GET_BY_ID, (post_id,))
        row = cur.fetchone()
    return _from_row(row) if row else None


def get_by_external_ref(db: Database, external_ref: str) -> Post | None:
    """Return the post with this platform-minted external reference, or ``None``."""
    with db.cursor() as cur:
        cur.execute(sql.GET_BY_EXTERNAL_REF, (external_ref,))
        row = cur.fetchone()
    return _from_row(row) if row else None


def increment_poll_count(db: Database, external_ref: str) -> None:
    """Bump the container's poll counter by 1."""
    with db.cursor() as cur:
        cur.execute(sql.INCREMENT_POLL_COUNT, (external_ref,))


def list_by_external_refs(db: Database, refs: list[str]) -> list[Post]:
    """Fetch posts for a set of ``external_ref`` values, in DB order.

    Sized for carousel children (≤10 refs). The query expands one ``?`` per
    ref via :data:`sql.LIST_BY_EXTERNAL_REFS`, so very large lists can hit
    SQLite's variable-count limit (default 999). Callers that need bulk
    lookups should batch.
    """
    if not refs:
        return []
    placeholders = ",".join("?" for _ in refs)
    stmt = sql.LIST_BY_EXTERNAL_REFS.format(placeholders=placeholders)
    with db.cursor() as cur:
        cur.execute(stmt, refs)
        rows = cur.fetchall()
    return [_from_row(r) for r in rows]


def list_recent(
    db: Database,
    *,
    limit: int = 50,
    platform: str | None = None,
    q: str | None = None,
    status: PostStatus | None = None,
) -> list[Post]:
    """Return up to ``limit`` posts ordered by ``created_at`` descending.

    ``platform``, ``status``, and ``q`` are optional ``WHERE`` predicates
    pushed into SQL — without them, in-Python filtering on a 50-row slice
    would silently lie once the table outgrows the slice (sidebar counts
    would show real totals, the list would show 50-row slices). All
    three are bound by name so the same statement handles every
    combination.

    ``q`` is a substring search across caption, ``account_id``, and the
    joined ``accounts.username``. Blank or whitespace-only values are
    treated as no search. SQLite's LIKE is ASCII-case-insensitive, which
    matches the platform/content scope here; non-ASCII captions would
    need a different strategy.
    """
    with db.cursor() as cur:
        cur.execute(
            sql.LIST_RECENT,
            {
                "platform": platform,
                "status": status,
                "like_q": like_needle(q),
                "limit": limit,
            },
        )
        rows = cur.fetchall()
    return [_from_row(r) for r in rows]


def mark_failed(db: Database, post_id: str, reason: str) -> Post | None:
    """Transition ``post_id`` to ``failed`` with the given reason; ``None`` if missing."""
    with db.cursor() as cur:
        cur.execute(sql.MARK_FAILED, (reason, post_id))
        if cur.rowcount == 0:
            return None
        cur.execute(sql.GET_BY_ID, (post_id,))
        row = cur.fetchone()
    return _from_row(row) if row else None


def mark_published(db: Database, post_id: str) -> Post | None:
    """Transition ``post_id`` to ``published`` with current timestamp; ``None`` if missing."""
    with db.cursor() as cur:
        cur.execute(sql.MARK_PUBLISHED, (_iso(datetime.now(UTC)), post_id))
        if cur.rowcount == 0:
            return None
        cur.execute(sql.GET_BY_ID, (post_id,))
        row = cur.fetchone()
    return _from_row(row) if row else None


def mark_published_by_external_ref(
    db: Database, external_ref: str, platform_post_id: str
) -> Post | None:
    """Transition the post with this external_ref to ``published``; ``None`` if missing.

    Used by both Instagram (container_id) and TikTok (publish_id) publish
    flows — the client passes the platform-minted intermediate id and we
    mint the final ``platform_post_id``.
    """
    with db.cursor() as cur:
        cur.execute(
            sql.MARK_PUBLISHED_BY_EXTERNAL_REF,
            (_iso(datetime.now(UTC)), platform_post_id, external_ref),
        )
        if cur.rowcount == 0:
            return None
        cur.execute(sql.GET_BY_EXTERNAL_REF, (external_ref,))
        row = cur.fetchone()
    return _from_row(row) if row else None


def set_container_status_by_external_ref(
    db: Database, external_ref: str, status: ContainerStatus
) -> None:
    """Pin the container's ``status_code`` (FINISHED, EXPIRED, ERROR, IN_PROGRESS)."""
    with db.cursor() as cur:
        cur.execute(sql.SET_CONTAINER_STATUS_BY_EXTERNAL_REF, (status, external_ref))


def set_inject_failure_by_external_ref(db: Database, external_ref: str, kind: str | None) -> None:
    """Arm a failure injection on the next IG call against this container."""
    with db.cursor() as cur:
        cur.execute(sql.SET_INJECT_FAILURE_BY_EXTERNAL_REF, (kind, external_ref))


def _from_row(row: sqlite3.Row) -> Post:
    """Hydrate a :class:`Post` from a ``posts`` table row."""
    media = _parse_media_items(row["media_items"])
    if not media and row["media_url"]:
        media = [Media(ordinal=0, kind=row["media_type"] or "IMAGE", url=row["media_url"])]

    children_raw = row["child_container_ids"]
    children = [c for c in (children_raw or "").split(",") if c]

    return Post(
        id=row["id"],
        platform=row["platform"],
        account_id=row["account_id"],
        caption=row["caption"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        published_at=_parse_iso(row["published_at"]),
        failure_reason=row["failure_reason"],
        external_ref=row["external_ref"],
        media_url=row["media_url"],
        media_type=row["media_type"],
        platform_post_id=row["platform_post_id"],
        media=media,
        container_status=row["container_status"] or "IN_PROGRESS",
        poll_count=row["poll_count"] or 0,
        poll_threshold=row["poll_threshold"] or 0,
        inject_next_failure_kind=row["inject_next_failure_kind"],
        is_carousel_item=bool(row["is_carousel_item"]),
        child_container_ids=children,
    )


def _iso(dt: datetime) -> str:
    """Serialize a datetime as ISO 8601 for storage in a TEXT column."""
    return dt.isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    """Parse an optional ISO 8601 string back into a datetime."""
    return datetime.fromisoformat(s) if s else None


def _parse_media_items(raw: str | None) -> list[Media]:
    """Decode the ``media_items`` JSON column into an ordered list of :class:`Media`."""
    if not raw:
        return []
    items = json.loads(raw)
    return [Media(ordinal=i["ordinal"], kind=i["kind"], url=i["url"]) for i in items]
