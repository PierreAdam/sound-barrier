import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def call(client: AsyncClient, user: SubsonicUser, method: str, **params: str) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    return response.json()["subsonic-response"]


def new_name() -> str:
    return f"new-{uuid.uuid4().hex[:8]}"


async def test_admin_creates_users_with_roles(client: AsyncClient, admin: SubsonicUser) -> None:
    name = new_name()
    data = await call(client, admin, "createUser", username=name, password="pw", email="a@b.c")
    assert data["status"] == "ok"

    users = (await call(client, admin, "getUsers"))["users"]["user"]
    created = next(u for u in users if u["username"] == name)
    assert created["adminRole"] is False
    assert created["streamRole"] and created["downloadRole"] and created["playlistRole"]
    assert created["email"] == "a@b.c"

    # The new user can sign in with the password (also sent hex-encoded by some clients).
    assert (await call(client, SubsonicUser(name, "pw"), "ping"))["status"] == "ok"

    other = new_name()
    await call(
        client, admin, "createUser", username=other, password="enc:" + b"x".hex(), adminRole="true"
    )
    assert (await call(client, SubsonicUser(other, "x"), "getUsers"))["status"] == "ok"  # admin


async def test_duplicate_and_invalid_users(client: AsyncClient, admin: SubsonicUser) -> None:
    data = await call(client, admin, "createUser", username=admin.username, password="pw")
    assert data["error"]["code"] == 0
    assert "already exists" in data["error"]["message"]
    data = await call(client, admin, "createUser", username=new_name())
    assert data["error"]["code"] == 10  # password missing


async def test_regular_users_cannot_manage_users(client: AsyncClient, user: SubsonicUser) -> None:
    for method, params in [
        ("getUsers", {}),
        ("createUser", {"username": new_name(), "password": "pw"}),
        ("deleteUser", {"username": user.username}),
        ("updateUser", {"username": user.username, "adminRole": "true"}),
    ]:
        assert (await call(client, user, method, **params))["error"]["code"] == 50, method


async def test_change_role_and_password(
    client: AsyncClient, admin: SubsonicUser, user: SubsonicUser
) -> None:
    await call(client, admin, "updateUser", username=user.username, adminRole="true")
    assert (await call(client, user, "getUsers"))["status"] == "ok"
    await call(client, admin, "updateUser", username=user.username, adminRole="false")
    assert (await call(client, user, "getUsers"))["error"]["code"] == 50

    # Admin resets the password; the old one stops working.
    await call(client, admin, "updateUser", username=user.username, password="reset")
    assert (await call(client, user, "ping"))["error"]["code"] == 40
    assert (await call(client, SubsonicUser(user.username, "reset"), "ping"))["status"] == "ok"


async def test_change_own_password(
    client: AsyncClient, user: SubsonicUser, admin: SubsonicUser
) -> None:
    assert (await call(client, user, "changePassword", username=user.username, password="n3w"))[
        "status"
    ] == "ok"
    assert (await call(client, SubsonicUser(user.username, "n3w"), "ping"))["status"] == "ok"
    # ...but not someone else's.
    renamed = SubsonicUser(user.username, "n3w")
    data = await call(client, renamed, "changePassword", username=admin.username, password="x")
    assert data["error"]["code"] == 50


async def test_safety_rules(client: AsyncClient, admin: SubsonicUser, user: SubsonicUser) -> None:
    data = await call(client, admin, "deleteUser", username=admin.username)
    assert "own account" in data["error"]["message"]
    data = await call(client, admin, "updateUser", username=admin.username, adminRole="false")
    assert "own admin role" in data["error"]["message"]

    assert (await call(client, admin, "deleteUser", username=user.username))["status"] == "ok"
    assert (await call(client, admin, "getUser", username=user.username))["error"]["code"] == 70
