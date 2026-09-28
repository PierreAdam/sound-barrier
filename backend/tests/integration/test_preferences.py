import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

DEFAULTS = {
    "theme": {"mode": "dark", "accent": "teal"},
    "player": {"crossfade": False, "crossfadeSeconds": 5},
    "discography": {"categories": ["album"], "recentMonths": 6},
}


async def test_preferences_are_saved_per_user(
    app: FastAPI, user: SubsonicUser, admin: SubsonicUser
) -> None:
    async with signed_in(app, user) as client:
        assert (await client.get("/api/preferences")).json() == DEFAULTS
        wanted = {
            "theme": {"mode": "light", "accent": "violet"},
            "player": {"crossfade": True, "crossfadeSeconds": 8},
            "discography": {"categories": ["album", "album+live", "ep"], "recentMonths": 3},
        }
        response = await client.put("/api/preferences", json=wanted)
        assert response.json() == wanted
        assert (await client.get("/api/preferences")).json() == wanted

    # Another device: the same preferences. Another user: their own.
    async with signed_in(app, user) as client:
        assert (await client.get("/api/preferences")).json()["theme"]["mode"] == "light"
    async with signed_in(app, admin) as client:
        assert (await client.get("/api/preferences")).json() == DEFAULTS


@pytest.mark.parametrize(
    "bad",
    [
        {"theme": {"mode": "neon"}},
        {"theme": {"accent": "Not A Color!"}},
        {"player": {"crossfadeSeconds": 60}},
        {"discography": {"categories": ["Album; DROP"]}},
        {"discography": {"recentMonths": 13}},
    ],
)
async def test_invalid_preferences_are_refused(
    app: FastAPI, user: SubsonicUser, bad: dict[str, object]
) -> None:
    async with signed_in(app, user) as client:
        assert (await client.put("/api/preferences", json=bad)).status_code == 422


async def test_preferences_need_a_session(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/preferences")).status_code == 401
