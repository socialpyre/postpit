"""Tests for the Instagram publishing flow — container, status, publish."""

import httpx

from posthole.routes.platforms.instagram.exceptions import (
    ApplicationRateLimitedError,
    GenericRateLimitedError,
    MediaFormatUnsupportedError,
    MediaUnreachableError,
    PageRateLimitedError,
    PasswordChangedError,
    TokenExpiredError,
    TokenRevokedError,
    UserRateLimitedError,
)

ALICE = "178414000000001"  # test_studio, seeded by migration 0001


async def test_create_container_returns_id(client: httpx.AsyncClient, ig_access_token: str) -> None:
    response = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/1.jpg", "caption": "hi"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["id"].startswith("mock-container-")


async def test_create_container_requires_image_url(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    response = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"caption": "no image"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["error_subcode"] == 2207001


async def test_create_container_rejects_unsupported_media_type(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """Singleton-create only accepts IMAGE; VIDEO / REELS still come later."""
    response = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/1.jpg", "media_type": "VIDEO"},
    )

    assert response.status_code == 400


async def test_create_container_without_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/{ALICE}/media",
        data={"image_url": "https://img/1.jpg"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == 190


async def test_create_container_with_unknown_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/{ALICE}/media",
        params={"access_token": "mock-short-not-a-real-token"},
        data={"image_url": "https://img/1.jpg"},
    )

    assert response.status_code == 401


async def test_container_status_finished(client: httpx.AsyncClient, ig_access_token: str) -> None:
    container = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/1.jpg"},
    )
    container_id = container.json()["id"]

    status = await client.get(f"/{container_id}", params={"access_token": ig_access_token})

    body = status.json()
    assert status.status_code == 200
    assert body["status_code"] == "FINISHED"
    assert body["media_type"] == "IMAGE"
    assert body["media_product_type"] == "FEED"


async def test_container_status_unknown_returns_404(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    response = await client.get(
        "/mock-container-does-not-exist", params={"access_token": ig_access_token}
    )

    assert response.status_code == 404


async def test_container_status_without_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/mock-container-anything")

    assert response.status_code == 401


async def test_publish_marks_post_published(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    container = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/1.jpg", "caption": "go live"},
    )
    container_id = container.json()["id"]

    publish = await client.post(
        f"/{ALICE}/media_publish",
        params={"access_token": ig_access_token},
        data={"creation_id": container_id},
    )

    body = publish.json()
    assert publish.status_code == 200
    assert body["id"].startswith("mock-post-")


async def test_publish_unknown_container_returns_404(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    response = await client.post(
        f"/{ALICE}/media_publish",
        params={"access_token": ig_access_token},
        data={"creation_id": "mock-container-nope"},
    )

    assert response.status_code == 404


async def test_publish_without_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/{ALICE}/media_publish",
        data={"creation_id": "mock-container-anything"},
    )

    assert response.status_code == 401


async def test_api_version_prefix_stripped(client: httpx.AsyncClient, ig_access_token: str) -> None:
    """``/v22.0/{user_id}/media`` should resolve to the bare publishing route."""
    response = await client.post(
        f"/v22.0/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/v22.jpg", "caption": "via versioned URL"},
    )

    assert response.status_code == 200
    assert response.json()["id"].startswith("mock-container-")


# ---------- PH.2 — realistic polling ----------


async def test_container_polling_ramps_to_finished(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """``delay_polls=3`` requires 3 GETs before flipping IN_PROGRESS → FINISHED."""
    create = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/poll.jpg", "delay_polls": 3},
    )
    container_id = create.json()["id"]

    statuses = []
    for _ in range(3):
        r = await client.get(f"/{container_id}", params={"access_token": ig_access_token})
        statuses.append(r.json()["status_code"])

    assert statuses == ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]

    # Sticky once flipped.
    stuck = await client.get(f"/{container_id}", params={"access_token": ig_access_token})
    assert stuck.json()["status_code"] == "FINISHED"


# ---------- PH.3 — failure injection ----------


async def test_caption_sentinel_arms_failure_and_strips_caption(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """``[posthole:fail=rate_limited]`` in the caption arms the next call."""
    create = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={
            "image_url": "https://img/x.jpg",
            "caption": "hello [posthole:fail=rate_limited] world",
        },
    )
    assert create.status_code == 200
    container_id = create.json()["id"]

    poll = await client.get(f"/{container_id}", params={"access_token": ig_access_token})
    body = poll.json()
    assert poll.status_code == 400
    assert body["error"]["code"] == 17  # UserRateLimitedError

    # Second poll is clean — the injection is one-shot.
    poll2 = await client.get(f"/{container_id}", params={"access_token": ig_access_token})
    assert poll2.status_code == 200


async def test_header_injection_raises_immediately(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """``X-Posthole-Inject-Failure: media_unreachable`` raises on the request that carries it."""
    create = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/x.jpg"},
    )
    container_id = create.json()["id"]

    poll = await client.get(
        f"/{container_id}",
        params={"access_token": ig_access_token},
        headers={"X-Posthole-Inject-Failure": "media_unreachable"},
    )

    body = poll.json()
    assert poll.status_code == 400
    assert body["error"]["code"] == 100
    assert body["error"]["error_subcode"] == 2207026


# ---------- PH.4 — error-code coverage ----------


def test_new_error_subclasses_serialize_correctly() -> None:
    """Smoke-test every PH.4 subclass renders its code/subcode through the Meta envelope."""
    cases = [
        (ApplicationRateLimitedError(), 4, None),
        (UserRateLimitedError(), 17, None),
        (PageRateLimitedError(), 32, None),
        (GenericRateLimitedError(), 613, None),
        (MediaUnreachableError(), 100, 2207026),
        (MediaFormatUnsupportedError(), 100, 9004),
        (PasswordChangedError(), 190, 460),
        (TokenExpiredError(), 190, 463),
        (TokenRevokedError(), 190, 467),
    ]
    for exc, expected_code, expected_subcode in cases:
        response = exc.to_response()
        body = bytes(response.body).decode()
        assert f'"code":{expected_code}' in body, f"{type(exc).__name__} missing code"
        if expected_subcode is not None:
            assert f'"error_subcode":{expected_subcode}' in body, (
                f"{type(exc).__name__} missing subcode"
            )


# ---------- PH.5 — EXPIRED status + publish gating ----------


async def test_expired_injection_flips_status_and_blocks_publish(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """Injecting ``expired`` flips status_code to EXPIRED; publish then fails."""
    create = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={
            "image_url": "https://img/expire.jpg",
            "caption": "soon to expire [posthole:fail=expired]",
        },
    )
    container_id = create.json()["id"]

    # First poll consumes the injection and raises ContainerExpiredError.
    poll1 = await client.get(f"/{container_id}", params={"access_token": ig_access_token})
    assert poll1.status_code == 400
    assert poll1.json()["error"]["error_subcode"] == 2207027

    # Subsequent polls report the persisted EXPIRED status (no injection re-fire).
    poll2 = await client.get(f"/{container_id}", params={"access_token": ig_access_token})
    assert poll2.status_code == 200
    assert poll2.json()["status_code"] == "EXPIRED"

    # /media_publish refuses an EXPIRED container.
    publish = await client.post(
        f"/{ALICE}/media_publish",
        params={"access_token": ig_access_token},
        data={"creation_id": container_id},
    )
    assert publish.status_code == 400
    assert publish.json()["error"]["error_subcode"] == 2207027


async def test_publish_refuses_in_progress_container(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """A container that hasn't reached FINISHED can't be published."""
    create = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/slow.jpg", "delay_polls": 5},
    )
    container_id = create.json()["id"]

    publish = await client.post(
        f"/{ALICE}/media_publish",
        params={"access_token": ig_access_token},
        data={"creation_id": container_id},
    )
    assert publish.status_code == 400
    # ContainerNotReadyError uses the same wire shape as ContainerExpiredError.
    assert publish.json()["error"]["error_subcode"] == 2207027


# ---------- PH.1 — carousel containers ----------


async def _create_image_child(
    client: httpx.AsyncClient, token: str, url: str = "https://img/c.jpg"
) -> str:
    """Helper — create one image child container and return its id."""
    r = await client.post(
        f"/{ALICE}/media",
        params={"access_token": token},
        data={"image_url": url, "is_carousel_item": "true"},
    )
    assert r.status_code == 200
    return r.json()["id"]


async def test_carousel_create_publish_round_trip(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """Create 3 children, wrap in a CAROUSEL parent, publish the parent."""
    children_ids = [
        await _create_image_child(client, ig_access_token, f"https://img/c{i}.jpg")
        for i in range(3)
    ]

    parent_resp = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
            "caption": "three frames",
        },
    )
    assert parent_resp.status_code == 200
    parent_id = parent_resp.json()["id"]

    # Parent reports FINISHED (default delay_polls=0 on every container).
    status = await client.get(f"/{parent_id}", params={"access_token": ig_access_token})
    assert status.json()["status_code"] == "FINISHED"
    assert status.json()["media_type"] == "CAROUSEL"

    publish = await client.post(
        f"/{ALICE}/media_publish",
        params={"access_token": ig_access_token},
        data={"creation_id": parent_id},
    )
    assert publish.status_code == 200
    assert publish.json()["id"].startswith("mock-post-")


async def test_carousel_rejects_publishing_child_directly(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """Child containers can't be passed to /media_publish — Meta-style 2207020."""
    child_id = await _create_image_child(client, ig_access_token)

    publish = await client.post(
        f"/{ALICE}/media_publish",
        params={"access_token": ig_access_token},
        data={"creation_id": child_id},
    )
    assert publish.status_code == 400
    body = publish.json()
    assert body["error"]["code"] == 100
    assert body["error"]["error_subcode"] == 2207020


async def test_carousel_parent_aggregates_in_progress_from_children(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """If any child is IN_PROGRESS, the parent reports IN_PROGRESS."""
    # Two children: one ready immediately, one with a poll ramp.
    fast = await _create_image_child(client, ig_access_token, "https://img/fast.jpg")
    slow_resp = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={
            "image_url": "https://img/slow.jpg",
            "is_carousel_item": "true",
            "delay_polls": 2,
        },
    )
    slow = slow_resp.json()["id"]

    parent_resp = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"media_type": "CAROUSEL", "children": f"{fast},{slow}", "caption": "mixed"},
    )
    parent_id = parent_resp.json()["id"]

    # Slow child is still IN_PROGRESS — parent inherits.
    parent_status = await client.get(f"/{parent_id}", params={"access_token": ig_access_token})
    assert parent_status.json()["status_code"] == "IN_PROGRESS"

    # Advance slow child to FINISHED, then re-poll parent.
    for _ in range(2):
        await client.get(f"/{slow}", params={"access_token": ig_access_token})
    parent_status2 = await client.get(f"/{parent_id}", params={"access_token": ig_access_token})
    assert parent_status2.json()["status_code"] == "FINISHED"


async def test_carousel_create_rejects_unknown_child(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """A children= id that doesn't exist returns 400."""
    response = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={
            "media_type": "CAROUSEL",
            "children": "mock-container-does-not-exist,mock-container-also-not",
            "caption": "broken",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == 100


async def test_carousel_create_rejects_non_child_in_children(
    client: httpx.AsyncClient, ig_access_token: str
) -> None:
    """``children=`` ids must each carry ``is_carousel_item=true``."""
    # Create one regular (non-carousel-item) container.
    plain = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"image_url": "https://img/plain.jpg"},
    )
    plain_id = plain.json()["id"]

    child2 = await _create_image_child(client, ig_access_token)

    response = await client.post(
        f"/{ALICE}/media",
        params={"access_token": ig_access_token},
        data={"media_type": "CAROUSEL", "children": f"{plain_id},{child2}"},
    )
    assert response.status_code == 400
