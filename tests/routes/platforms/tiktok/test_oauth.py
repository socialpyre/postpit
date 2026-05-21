"""Tests for the TikTok OAuth flow — authorize, token exchange, /user/info."""

from urllib.parse import parse_qs, urlparse

import httpx

CREATOR = "tt-7000000000000000001"  # test_creator, seeded by migration 0002


async def _access_token(client: httpx.AsyncClient, account_id: str = CREATOR) -> str:
    """Walk authorize → code → token; return the access token."""
    auth = await client.post(
        "/auth/authorize/",
        data={"account_id": account_id, "redirect_uri": "http://localhost/cb", "state": "xyz"},
        follow_redirects=False,
    )
    assert auth.status_code == 302
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

    token = await client.post(
        "/oauth/token/",
        data={
            "client_key": "demo",
            "client_secret": "demo",
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": "http://localhost/cb",
        },
    )
    assert token.status_code == 200
    return token.json()["access_token"]


async def test_authorize_picker_lists_only_tiktok_accounts(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/auth/authorize/",
        params={"client_key": "demo", "redirect_uri": "http://localhost/cb", "state": "xyz"},
    )

    body = response.text
    assert response.status_code == 200
    # TikTok accounts present (seeded by migration 0002)
    assert "test_creator" in body
    assert "test_brand" in body
    # IG accounts absent — picker filters by platform
    assert "test_studio" not in body
    assert "test_artist" not in body


async def test_authorize_post_redirects_with_code(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/authorize/",
        data={"account_id": CREATOR, "redirect_uri": "http://localhost/cb", "state": "xyz"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert "code" in query
    assert query["state"] == ["xyz"]


async def test_authorize_post_rejects_ig_account(client: httpx.AsyncClient) -> None:
    """An IG account_id presented to the TikTok picker is rejected."""
    response = await client.post(
        "/auth/authorize/",
        data={"account_id": "178414000000001", "redirect_uri": "http://localhost/cb", "state": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_param"


async def test_token_exchange_returns_dual_token(client: httpx.AsyncClient) -> None:
    access = await _access_token(client)
    # Walk again to get both halves for assertion
    auth = await client.post(
        "/auth/authorize/",
        data={"account_id": CREATOR, "redirect_uri": "http://localhost/cb", "state": ""},
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    token_resp = await client.post(
        "/oauth/token/",
        data={
            "client_key": "k",
            "client_secret": "s",
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    body = token_resp.json()

    assert access.startswith("act.")
    assert body["access_token"].startswith("act.")
    assert body["refresh_token"].startswith("rft.")
    assert body["token_type"] == "Bearer"  # noqa: S105
    assert body["expires_in"] == 86400
    assert body["refresh_expires_in"] == 31536000
    assert body["open_id"] == CREATOR


async def test_refresh_token_grant_rotates(client: httpx.AsyncClient) -> None:
    """grant_type=refresh_token returns a fresh access+refresh pair."""
    # Get an initial pair
    auth = await client.post(
        "/auth/authorize/",
        data={"account_id": CREATOR, "redirect_uri": "http://localhost/cb", "state": ""},
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    first = await client.post(
        "/oauth/token/",
        data={"code": code, "grant_type": "authorization_code"},
    )
    refresh_token = first.json()["refresh_token"]

    # Use the refresh token to mint a new pair
    second = await client.post(
        "/oauth/token/",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )

    body = second.json()
    assert second.status_code == 200
    assert body["access_token"] != first.json()["access_token"]
    assert body["refresh_token"] != refresh_token


async def test_token_exchange_rejects_bad_code(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/oauth/token/",
        data={"code": "bogus", "grant_type": "authorization_code"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_grant"


async def test_user_info_returns_account(client: httpx.AsyncClient) -> None:
    token = await _access_token(client)

    response = await client.get(
        "/user/info/",
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["error"]["code"] == "ok"
    assert body["data"]["user"]["open_id"] == CREATOR
    assert body["data"]["user"]["display_name"] == "Test Creator"


async def test_user_info_honors_fields_filter(client: httpx.AsyncClient) -> None:
    token = await _access_token(client)

    response = await client.get(
        "/user/info/",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "open_id,display_name"},
    )

    user = response.json()["data"]["user"]
    assert set(user.keys()) == {"open_id", "display_name"}


async def test_user_info_rejects_missing_bearer(client: httpx.AsyncClient) -> None:
    response = await client.get("/user/info/")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "access_token_invalid"


async def test_authorize_post_rejects_javascript_scheme(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/authorize/",
        data={"account_id": CREATOR, "redirect_uri": "javascript:alert(1)", "state": ""},
        follow_redirects=False,
    )

    assert response.status_code == 400


async def test_user_info_rejects_ig_token(client: httpx.AsyncClient) -> None:
    """An IG-issued token presented to /user/info should be rejected by platform check."""
    # Issue an IG token via the IG flow
    ig_auth = await client.post(
        "/oauth/authorize",
        data={"account_id": "178414000000001", "redirect_uri": "http://localhost/cb", "state": ""},
        follow_redirects=False,
    )
    ig_code = parse_qs(urlparse(ig_auth.headers["location"]).query)["code"][0]
    ig_token_resp = await client.post(
        "/oauth/access_token",
        data={"code": ig_code, "grant_type": "authorization_code"},
    )
    ig_token = ig_token_resp.json()["access_token"]

    # Present it to TikTok's /user/info/ — should 404 (token resolves to IG account)
    response = await client.get(
        "/user/info/",
        headers={"Authorization": f"Bearer {ig_token}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"
