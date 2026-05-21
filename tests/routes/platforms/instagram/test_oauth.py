"""Tests for the Instagram OAuth flow — authorize, token exchange, /me."""

from urllib.parse import parse_qs, urlparse

import httpx

ALICE = "178414000000001"  # test_studio, seeded by migration 0001


async def _short_token(client: httpx.AsyncClient, account_id: str = ALICE) -> str:
    """Walk authorize → code → access_token; return the short-lived token."""
    auth = await client.post(
        "/oauth/authorize",
        data={
            "account_id": account_id,
            "redirect_uri": "http://localhost/cb",
            "state": "xyz",
        },
        follow_redirects=False,
    )
    assert auth.status_code == 303
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

    token = await client.post(
        "/oauth/access_token",
        data={"code": code, "grant_type": "authorization_code"},
    )
    assert token.status_code == 200
    return token.json()["access_token"]


async def test_authorize_picker_lists_seeded_accounts(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/oauth/authorize",
        params={"client_id": "demo", "redirect_uri": "http://localhost/cb", "state": "xyz"},
    )

    assert response.status_code == 200
    body = response.text
    assert "test_studio" in body
    assert "test_artist" in body


async def test_authorize_post_redirects_with_code(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oauth/authorize",
        data={
            "account_id": ALICE,
            "redirect_uri": "http://localhost/cb",
            "state": "xyz",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    parsed = urlparse(response.headers["location"])
    query = parse_qs(parsed.query)
    assert "code" in query
    assert query["state"] == ["xyz"]


async def test_authorize_post_rejects_unknown_account(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oauth/authorize",
        data={"account_id": "nope", "redirect_uri": "http://localhost/cb", "state": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == 100


async def test_code_exchange_issues_short_token(client: httpx.AsyncClient) -> None:
    token = await _short_token(client)

    assert token.startswith("mock-short-")


async def test_code_is_one_shot(client: httpx.AsyncClient) -> None:
    """Re-presenting a consumed code fails with a Meta-shaped 400."""
    auth = await client.post(
        "/oauth/authorize",
        data={"account_id": ALICE, "redirect_uri": "http://localhost/cb", "state": "x"},
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

    first = await client.post(
        "/oauth/access_token",
        data={"code": code, "grant_type": "authorization_code"},
    )
    second = await client.post(
        "/oauth/access_token",
        data={"code": code, "grant_type": "authorization_code"},
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["type"] == "OAuthException"


async def test_short_to_long_token_exchange(client: httpx.AsyncClient) -> None:
    short = await _short_token(client)

    response = await client.get(
        "/access_token",
        params={"grant_type": "ig_exchange_token", "access_token": short},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["access_token"].startswith("mock-long-")
    assert body["token_type"] == "bearer"  # noqa: S105
    assert body["expires_in"] == 5184000


async def test_refresh_long_token(client: httpx.AsyncClient) -> None:
    short = await _short_token(client)
    long_resp = await client.get(
        "/access_token",
        params={"grant_type": "ig_exchange_token", "access_token": short},
    )
    long_token = long_resp.json()["access_token"]

    refreshed = await client.get(
        "/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": long_token},
    )

    body = refreshed.json()
    assert refreshed.status_code == 200
    assert body["access_token"].startswith("mock-long-")
    assert body["access_token"] != long_token  # rotated


async def test_refresh_rejects_short_token(client: httpx.AsyncClient) -> None:
    short = await _short_token(client)

    response = await client.get(
        "/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": short},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == 190


async def test_me_returns_account_info(client: httpx.AsyncClient) -> None:
    short = await _short_token(client)

    response = await client.get("/me", params={"access_token": short})

    body = response.json()
    assert response.status_code == 200
    assert body["user_id"] == ALICE
    assert body["username"] == "test_studio"
    assert body["account_type"] == "BUSINESS"


async def test_me_rejects_invalid_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/me", params={"access_token": "not-a-token"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == 190


async def test_authorize_post_rejects_javascript_scheme(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oauth/authorize",
        data={"account_id": ALICE, "redirect_uri": "javascript:alert(1)", "state": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400
