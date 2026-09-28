from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.crypto import subsonic_token
from app.services import music_folders, users
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


def body(response: Any) -> dict[str, Any]:
    assert response.status_code == 200
    return response.json()["subsonic-response"]


async def test_ping_with_password(client: AsyncClient, user: SubsonicUser) -> None:
    data = body(await client.get("/rest/ping", params=user.params()))
    assert data["status"] == "ok"
    assert data["openSubsonic"] is True


async def test_ping_with_token_and_view_suffix(client: AsyncClient, user: SubsonicUser) -> None:
    params = user.params(t=subsonic_token(user.password, "abc123"), s="abc123")
    del params["p"]
    assert body(await client.get("/rest/ping.view", params=params))["status"] == "ok"


async def test_ping_form_post(client: AsyncClient, user: SubsonicUser) -> None:
    assert body(await client.post("/rest/ping", data=user.params()))["status"] == "ok"


async def test_default_format_is_xml(client: AsyncClient, user: SubsonicUser) -> None:
    params = user.params()
    del params["f"]
    response = await client.get("/rest/ping", params=params)
    assert response.headers["content-type"].startswith("application/xml")
    assert ElementTree.fromstring(response.content).get("status") == "ok"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"p": "wrong"}, 40),
        ({"u": "nobody"}, 40),
        ({"u": ""}, 10),
    ],
)
async def test_auth_failures(
    client: AsyncClient, user: SubsonicUser, override: dict[str, str], code: int
) -> None:
    data = body(await client.get("/rest/ping", params=user.params(**override)))
    assert data["status"] == "failed"
    assert data["error"]["code"] == code


async def test_api_key_auth(client: AsyncClient, app: FastAPI, user: SubsonicUser) -> None:
    async with app.state.db.session() as session:
        db_user = await users.get_by_username(session, user.username)
        assert db_user is not None
        key = await users.create_api_key(session, db_user, "tests")
        await session.commit()

    params = {"apiKey": key, "v": "1.16.1", "c": "tests", "f": "json"}
    assert body(await client.get("/rest/ping", params=params))["status"] == "ok"

    data = body(await client.get("/rest/ping", params={**params, "u": user.username}))
    assert data["error"]["code"] == 43
    data = body(await client.get("/rest/ping", params={**params, "apiKey": "bogus"}))
    assert data["error"]["code"] == 44


async def test_open_subsonic_extensions_is_public(client: AsyncClient) -> None:
    data = body(await client.get("/rest/getOpenSubsonicExtensions", params={"f": "json"}))
    names = {ext["name"] for ext in data["openSubsonicExtensions"]}
    assert {"apiKeyAuthentication", "formPost"} <= names


async def test_get_license(client: AsyncClient, user: SubsonicUser) -> None:
    assert body(await client.get("/rest/getLicense", params=user.params()))["license"]["valid"]


async def test_get_music_folders(
    client: AsyncClient, app: FastAPI, user: SubsonicUser, tmp_path: Path
) -> None:
    async with app.state.db.session() as session:
        folder = await music_folders.create(session, "Test library", tmp_path)
        await session.commit()

    data = body(await client.get("/rest/getMusicFolders", params=user.params()))
    assert {"id": folder.id, "name": "Test library"} in data["musicFolders"]["musicFolder"]


async def test_get_user(client: AsyncClient, user: SubsonicUser, admin: SubsonicUser) -> None:
    data = body(await client.get("/rest/getUser", params=user.params(username=user.username)))
    assert data["user"]["username"] == user.username
    assert data["user"]["adminRole"] is False
    assert data["user"]["streamRole"] is True

    # A regular user cannot read another user; an admin can.
    data = body(await client.get("/rest/getUser", params=user.params(username=admin.username)))
    assert data["error"]["code"] == 50
    data = body(await client.get("/rest/getUser", params=admin.params(username=user.username)))
    assert data["user"]["username"] == user.username

    data = body(await client.get("/rest/getUser", params=admin.params(username="nobody")))
    assert data["error"]["code"] == 70


async def test_unknown_method(client: AsyncClient, user: SubsonicUser) -> None:
    data = body(await client.get("/rest/getVideos.view", params=user.params()))
    assert data["status"] == "failed"
    assert data["error"]["code"] == 70
