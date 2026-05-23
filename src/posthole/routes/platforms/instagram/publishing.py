"""Instagram publishing route handlers — container, status, publish.

IG Graph's publishing flow is two-step:

    POST /{user_id}/media       → creates a "container" with the media URL
    GET  /{container_id}        → poll for FINISHED status (we return immediately)
    POST /{user_id}/media_publish (creation_id=...) → flip to published

Note: ``GET /{container_id}`` is a single-segment wildcard at the root, so the
IG router must be registered AFTER the UI router in ``main.py`` — otherwise
``/accounts`` would resolve here as a missing container.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Form, Header, Query

from posthole.db import DbDep, posts
from posthole.routes.platforms.instagram.auth import require_access_token
from posthole.routes.platforms.instagram.exceptions import (
    CarouselChildInvalidError,
    CarouselChildPublishError,
    ContainerExpiredError,
    ContainerNotFoundError,
    ContainerNotReadyError,
    MissingImageUrlError,
    UnsupportedMediaTypeError,
)
from posthole.routes.platforms.instagram.injection import (
    extract_caption_sentinel,
    header_injection_kind,
    raise_for_kind,
)
from posthole.routes.platforms.instagram.responses import META_ERROR_RESPONSES

router = APIRouter(tags=["instagram-publishing"], responses=META_ERROR_RESPONSES)


@router.post("/{user_id}/media")
async def create_container(
    user_id: str,
    db: DbDep,
    access_token: Annotated[str, Query()] = "",
    access_token_form: Annotated[str, Form(alias="access_token")] = "",
    image_url: Annotated[str, Form()] = "",
    caption: Annotated[str, Form()] = "",
    media_type: Annotated[str, Form()] = "IMAGE",
    is_carousel_item: Annotated[bool, Form()] = False,
    children: Annotated[str, Form()] = "",
    delay_polls: Annotated[int, Form()] = 0,
    inject_failure_header: Annotated[str | None, Header(alias="X-Posthole-Inject-Failure")] = None,
) -> dict[str, str]:
    """Create a media container — IMAGE (singleton or carousel child) or CAROUSEL parent.

    ``delay_polls`` (form field) pins the polling threshold — 0 (default)
    means the next GET reports FINISHED immediately; higher values require
    that many polls before flipping.

    ``X-Posthole-Inject-Failure`` (header) arms a failure for the next call
    against the container being created; the caption sentinel
    ``[posthole:fail=<kind>]`` does the same and is stripped from the
    persisted caption. When both are present the sentinel wins — the header
    is silently dropped at create time.
    """
    require_access_token(db, access_token or access_token_form)

    cleaned_caption, sentinel_kind = extract_caption_sentinel(caption or None)
    inject_kind = sentinel_kind or header_injection_kind(inject_failure_header)

    if media_type == "CAROUSEL":
        return await _create_carousel_parent(
            db,
            user_id=user_id,
            caption=cleaned_caption,
            children=children,
            delay_polls=delay_polls,
            inject_kind=inject_kind,
        )
    if media_type != "IMAGE":
        msg = f"Unsupported media_type {media_type!r}"
        raise UnsupportedMediaTypeError(msg)
    if not image_url:
        raise MissingImageUrlError

    container_id = f"mock-container-{secrets.token_urlsafe(16)}"
    initial_status = "FINISHED" if delay_polls == 0 else "IN_PROGRESS"
    posts.create(
        db,
        platform="instagram",
        account_id=user_id,
        # Carousel children don't carry their own caption — IG mandates the
        # caption live on the parent. Drop any caption a client sends on a
        # child container even if non-empty. A ``[posthole:fail=...]`` sentinel
        # in that dropped caption was already extracted above into ``inject_kind``,
        # so failure injection on a child still works via the caption channel.
        caption=None if is_carousel_item else cleaned_caption,
        external_ref=container_id,
        media_url=image_url,
        media_type="IMAGE",
        container_status=initial_status,
        poll_threshold=delay_polls,
        inject_next_failure_kind=inject_kind,
        is_carousel_item=is_carousel_item,
    )
    return {"id": container_id}


@router.get("/{container_id}")
async def container_status(
    container_id: str,
    db: DbDep,
    access_token: Annotated[str, Query()] = "",
    inject_failure_header: Annotated[str | None, Header(alias="X-Posthole-Inject-Failure")] = None,
) -> dict[str, str]:
    """Return container status — IN_PROGRESS → FINISHED via polling, or EXPIRED/ERROR."""
    require_access_token(db, access_token)
    post = posts.get_by_external_ref(db, container_id)
    if post is None:
        msg = f"Container {container_id!r} not found"
        raise ContainerNotFoundError(msg)

    _consume_injection(db, post, inject_failure_header)

    if post.media_type == "CAROUSEL":
        status_code = _aggregate_carousel_status(db, post)
    else:
        status_code = _advance_polling(db, post)

    media_type = post.media_type or "IMAGE"
    return {
        "status_code": status_code,
        "media_type": media_type,
        "media_product_type": "FEED",
    }


@router.post("/{user_id}/media_publish")
async def publish(
    user_id: str,  # noqa: ARG001 — IG's URL shape; we publish by container_id
    db: DbDep,
    creation_id: Annotated[str, Form()],
    access_token: Annotated[str, Query()] = "",
    access_token_form: Annotated[str, Form(alias="access_token")] = "",
    inject_failure_header: Annotated[str | None, Header(alias="X-Posthole-Inject-Failure")] = None,
) -> dict[str, str]:
    """Flip a pending container to ``published`` and return its platform-side id.

    Refuses to publish:

    - Unknown ``creation_id`` → 404
    - Child container (``is_carousel_item=true``) → ``code=100, error_subcode=2207020``
    - Container in ``EXPIRED`` status → ``code=9007, error_subcode=2207027``
    - Container in any non-``FINISHED`` status → same expired-shape error
    """
    require_access_token(db, access_token or access_token_form)
    post = posts.get_by_external_ref(db, creation_id)
    if post is None:
        msg = f"Container {creation_id!r} not found"
        raise ContainerNotFoundError(msg)

    _consume_injection(db, post, inject_failure_header)

    if post.is_carousel_item:
        raise CarouselChildPublishError
    if post.container_status == "EXPIRED":
        raise ContainerExpiredError
    if post.container_status != "FINISHED":
        msg = f"Container {creation_id!r} is not ready to publish (status={post.container_status})"
        raise ContainerNotReadyError(msg)

    platform_post_id = f"mock-post-{secrets.token_urlsafe(16)}"
    posts.mark_published_by_external_ref(db, creation_id, platform_post_id)

    if post.media_type == "CAROUSEL" and post.child_container_ids:
        # Publishing a carousel parent publishes every child too — mints
        # one shared platform_post_id; real IG mints distinct media ids
        # per slide but clients typically only read the parent's id.
        for child_ref in post.child_container_ids:
            posts.mark_published_by_external_ref(db, child_ref, platform_post_id)

    return {"id": platform_post_id}


def _advance_polling(db: DbDep, post: posts.Post) -> str:
    """Increment poll counter for a single-media container and return the new status code.

    Terminal statuses (EXPIRED, ERROR, FINISHED-already) short-circuit
    without bumping the counter; only IN_PROGRESS containers ramp toward
    FINISHED via successive polls.

    Note: ``poll_threshold=0`` (phase-1 default) never reaches the counter
    bump — ``create_container`` stores ``container_status=FINISHED`` directly
    in that case, so the FINISHED short-circuit above returns first.
    """
    if post.container_status in {"EXPIRED", "ERROR"}:
        return post.container_status
    if post.container_status == "FINISHED":
        return "FINISHED"
    if post.external_ref is None:
        return post.container_status
    posts.increment_poll_count(db, post.external_ref)
    new_count = post.poll_count + 1
    if new_count >= post.poll_threshold:
        posts.set_container_status_by_external_ref(db, post.external_ref, "FINISHED")
        return "FINISHED"
    return "IN_PROGRESS"


def _aggregate_carousel_status(db: DbDep, parent: posts.Post) -> str:
    """Compute a carousel parent's reported status from its own + child statuses.

    Rules: any EXPIRED → EXPIRED. Any ERROR → ERROR. Any IN_PROGRESS (parent
    or child) → IN_PROGRESS. Otherwise FINISHED.
    """
    if parent.container_status in {"EXPIRED", "ERROR"}:
        return parent.container_status

    statuses: set[str] = {parent.container_status}
    if parent.child_container_ids:
        children = posts.list_by_external_refs(db, parent.child_container_ids)
        statuses.update(c.container_status for c in children)

    if "EXPIRED" in statuses:
        return "EXPIRED"
    if "ERROR" in statuses:
        return "ERROR"
    if "IN_PROGRESS" in statuses:
        return "IN_PROGRESS"
    return "FINISHED"


def _consume_injection(db: DbDep, post: posts.Post, header_value: str | None) -> None:
    """Apply any armed injection.

    Header takes precedence: when a recognized header is present, its kind
    is raised immediately and the function returns *without consuming* any
    persisted ``inject_next_failure_kind`` — that one stays armed for the
    next call. Only when no header is present do we consume and clear the
    persisted injection.
    """
    header_kind = header_injection_kind(header_value)
    if header_kind is not None:
        if header_kind == "expired" and post.external_ref is not None:
            posts.set_container_status_by_external_ref(db, post.external_ref, "EXPIRED")
        raise_for_kind(header_kind)

    if post.inject_next_failure_kind and post.external_ref is not None:
        kind = post.inject_next_failure_kind
        posts.clear_inject_failure_by_external_ref(db, post.external_ref)
        if kind == "expired":
            posts.set_container_status_by_external_ref(db, post.external_ref, "EXPIRED")
        raise_for_kind(kind)


async def _create_carousel_parent(
    db: DbDep,
    *,
    user_id: str,
    caption: str | None,
    children: str,
    delay_polls: int,
    inject_kind: str | None,
) -> dict[str, str]:
    """Validate + persist a CAROUSEL parent container referencing its children."""
    child_ids: list[str] = [c for c in (children or "").split(",") if c.strip()]
    if not child_ids:
        msg = "children= is required for media_type=CAROUSEL"
        raise CarouselChildInvalidError(msg)
    if len(child_ids) < 2 or len(child_ids) > 10:
        msg = f"CAROUSEL must reference 2-10 children (got {len(child_ids)})"
        raise CarouselChildInvalidError(msg)

    children_posts = posts.list_by_external_refs(db, child_ids)
    by_ref = {p.external_ref: p for p in children_posts}
    for ref in child_ids:
        child = by_ref.get(ref)
        if child is None:
            msg = f"Unknown carousel child container {ref!r}"
            raise CarouselChildInvalidError(msg)
        if not child.is_carousel_item:
            msg = f"Container {ref!r} is not flagged as a carousel item"
            raise CarouselChildInvalidError(msg)

    container_id = f"mock-container-{secrets.token_urlsafe(16)}"
    # Parent's own polling status is independent of its children — the
    # aggregate at read time gates on both. Start the parent at the same
    # initial state IMAGE containers do.
    initial_status = "FINISHED" if delay_polls == 0 else "IN_PROGRESS"
    # Copy each child's media item onto the parent so the inbox/detail
    # views render the carousel as a single multi-slide row (the row
    # template uses media|length for the slide-count badge, the detail
    # view's carousel controller iterates the same list). Ordered by the
    # position in children=. Children rows remain in storage for
    # publish-time aggregation but are filtered out of the inbox by
    # is_carousel_item=0 in db/sql/posts.py.
    parent_media: list[posts.Media] = []
    for ordinal, ref in enumerate(child_ids):
        child = by_ref[ref]
        slide = child.media[0] if child.media else None
        if slide is None:
            continue
        parent_media.append(posts.Media(ordinal=ordinal, kind=slide.kind, url=slide.url))
    posts.create(
        db,
        platform="instagram",
        account_id=user_id,
        caption=caption,
        external_ref=container_id,
        media_url=parent_media[0].url if parent_media else None,
        media_type="CAROUSEL",
        media=parent_media,
        container_status=initial_status,
        poll_threshold=delay_polls,
        inject_next_failure_kind=inject_kind,
        is_carousel_item=False,
        child_container_ids=child_ids,
    )
    return {"id": container_id}
