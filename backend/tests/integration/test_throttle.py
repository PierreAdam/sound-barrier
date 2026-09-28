from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.throttle import LoginThrottle
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


@pytest.fixture
def strict(app: FastAPI) -> Iterator[None]:
    real = app.state.throttle
    app.state.throttle = LoginThrottle(3)
    yield
    app.state.throttle = real


async def test_web_and_subsonic_sign_ins_are_throttled(
    app: FastAPI, client: AsyncClient, user: SubsonicUser, strict: None
) -> None:
    wrong = {"username": user.username, "password": "wrong"}
    for _ in range(2):
        assert (await client.post("/api/auth/login", json=wrong)).status_code == 401
    # The third failure, through the Subsonic API: counted too.
    bad = await client.get("/rest/ping", params={**user.params(), "p": "wrong"})
    assert bad.json()["subsonic-response"]["error"]["code"] == 40

    # Now refused, even with the right password, on both.
    right = {"username": user.username, "password": user.password}
    refused = await client.post("/api/auth/login", json=right)
    assert refused.status_code == 429
    assert "try again in 15 minutes" in refused.json()["detail"]
    data = (await client.get("/rest/ping", params=user.params())).json()["subsonic-response"]
    assert data["status"] == "failed" and "Too many failed sign-ins" in data["error"]["message"]

    # Another address is not affected.
    other = AsyncClient(
        transport=ASGITransport(app=app, client=("10.0.0.2", 1234)), base_url="http://test"
    )
    async with other:
        assert (await other.get("/rest/ping", params=user.params())).json()["subsonic-response"][
            "status"
        ] == "ok"
