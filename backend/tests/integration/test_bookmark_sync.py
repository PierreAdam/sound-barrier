"""The web player's bookmarks followed across devices (api/bookmarks.py): the latest of a
book, "moved" since what a device knew, and saves from an outdated position refused."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_spoken import spoken  # noqa: F401 (fixture)

pytestmark = pytest.mark.integration


async def _episodes(web: AsyncClient, kind: str, title: str) -> list[dict[str, Any]]:
    shows = (await web.get(f"/api/spoken/{kind}")).json()["shows"]
    show = next(s for s in shows if s["title"] == title)
    return (await web.get(f"/api/spoken/shows/{show['id']}")).json()["episodes"]


async def test_devices_follow_the_latest_bookmark_of_the_book(
    app: FastAPI,
    client: AsyncClient,
    user: SubsonicUser,
    spoken: dict[str, Path],  # noqa: F811
) -> None:
    async with signed_in(app, user) as pc, signed_in(app, user) as phone:
        one, two = (e["id"] for e in await _episodes(pc, "audiobooks", "A Book"))
        empty = (await pc.get("/api/bookmarks/latest", params={"song": one})).json()
        assert empty == {"bookmark": None, "moved": False}

        # The PC listens to the first file.
        saved = (
            await pc.put(f"/api/bookmarks/{one}", json={"positionMs": 60000, "source": "PC"})
        ).json()
        assert saved["saved"] is True
        pc_seen = saved["bookmark"]["changedAt"]

        # The phone carries on in the second file of the same book.
        latest = (await phone.get("/api/bookmarks/latest", params={"song": one})).json()
        assert latest["bookmark"]["source"] == "PC"
        moved_on = await phone.put(
            f"/api/bookmarks/{two}",
            json={"positionMs": 5000, "seen": latest["bookmark"]["changedAt"], "source": "Phone"},
        )
        assert moved_on.json()["saved"] is True

        # Back on the PC: the book moved (to the other file), and its old position is refused.
        check = (
            await pc.get("/api/bookmarks/latest", params={"song": one, "seen": pc_seen})
        ).json()
        assert check["moved"] is True
        assert (check["bookmark"]["songId"], check["bookmark"]["positionMs"]) == (two, 5000)
        assert check["bookmark"]["source"] == "Phone"
        stale = await pc.put(
            f"/api/bookmarks/{one}", json={"positionMs": 61000, "seen": pc_seen, "source": "PC"}
        )
        assert stale.json() == {"saved": False, "bookmark": check["bookmark"]}
        refused = await pc.delete(f"/api/bookmarks/{one}", params={"seen": pc_seen})
        assert refused.json()["saved"] is False

        # Once it has moved there, the PC saves again; the phone is then the one behind.
        phone_seen = moved_on.json()["bookmark"]["changedAt"]
        caught_up = await pc.put(
            f"/api/bookmarks/{two}",
            json={"positionMs": 9000, "seen": check["bookmark"]["changedAt"], "source": "PC"},
        )
        assert caught_up.json()["saved"] is True
        behind = (
            await phone.get("/api/bookmarks/latest", params={"song": two, "seen": phone_seen})
        ).json()
        assert behind["moved"] is True
        current = (
            await phone.get(
                "/api/bookmarks/latest",
                params={"song": two, "seen": caught_up.json()["bookmark"]["changedAt"]},
            )
        ).json()
        assert current["moved"] is False

        # Listened to the end: removed, with what the PC knew.
        done = await pc.delete(
            f"/api/bookmarks/{two}", params={"seen": caught_up.json()["bookmark"]["changedAt"]}
        )
        assert done.json()["saved"] is True
        # The first file's bookmark (refused removal above) is the book's latest again.
        assert done.json()["bookmark"]["songId"] == one

    # A Subsonic app's bookmark: its name as the source.
    await client.get("/rest/createBookmark", params=user.params(id=two, position="1000"))
    async with signed_in(app, user) as web:
        latest = (await web.get("/api/bookmarks/latest", params={"song": one})).json()
        assert (latest["bookmark"]["songId"], latest["bookmark"]["source"]) == (two, "tests")
        assert (
            await web.put(
                "/api/bookmarks/00000000-0000-4000-8000-000000000000", json={"positionMs": 1}
            )
        ).status_code == 404


async def test_podcast_episodes_are_followed_one_by_one(
    app: FastAPI,
    user: SubsonicUser,
    spoken: dict[str, Path],  # noqa: F811
) -> None:
    async with signed_in(app, user) as web:
        newest, older = (e["id"] for e in await _episodes(web, "podcasts", "The Show"))
        await web.put(f"/api/bookmarks/{older}", json={"positionMs": 4000})
        # Another episode's bookmark is not this one's.
        latest = (await web.get("/api/bookmarks/latest", params={"song": newest})).json()
        assert latest == {"bookmark": None, "moved": False}
        saved = (await web.put(f"/api/bookmarks/{newest}", json={"positionMs": 7000})).json()
        assert saved["saved"] is True and saved["bookmark"]["songId"] == newest
