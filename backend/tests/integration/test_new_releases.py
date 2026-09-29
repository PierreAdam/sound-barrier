"""New releases (Library Management), with MusicBrainz replaced by a fake transport."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete

from app.core.db import Database
from app.external import musicbrainz
from app.models import ArtistInfo, ServerSetting
from app.services import server_settings
from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_discography import AMON, TWILIGHT, FakeServices, _group, artists

pytestmark = pytest.mark.integration

__all__ = ["artists"]  # fixture

TODAY = datetime.now(UTC).date()
RECENT = "aaaaaaaa-0000-4000-8000-000000000001"
YEAR_ONLY = "aaaaaaaa-0000-4000-8000-000000000002"
OLD = "aaaaaaaa-0000-4000-8000-000000000003"
SOON = "aaaaaaaa-0000-4000-8000-000000000004"
LIVE_RECENT = "aaaaaaaa-0000-4000-8000-000000000005"


class FakeReleases(FakeServices):
    """Amon Amarth with releases around today."""

    def _musicbrainz(self, path: str, params: httpx.QueryParams) -> httpx.Response:
        if path == "release-group" and params["artist"] == AMON:
            groups: list[dict[str, Any]] = [
                _group(RECENT, "Recent One", (TODAY - timedelta(days=40)).isoformat(), "Album"),
                _group(YEAR_ONLY, "Year Only", str(TODAY.year), "Album"),
                _group(OLD, "Old One", (TODAY - timedelta(days=400)).isoformat(), "Album"),
                _group(SOON, "Soon", (TODAY + timedelta(days=20)).isoformat(), "Album"),
                _group(LIVE_RECENT, "Live Now", TODAY.isoformat(), "Album", "Live"),
                # In the library (a recent reissue of it would still be owned).
                _group(TWILIGHT, "Twilight of the Thunder God", TODAY.isoformat(), "Album"),
            ]
            return httpx.Response(200, json={"release-groups": groups, "release-group-count": 6})
        return super()._musicbrainz(path, params)


@pytest.fixture
async def services(
    app: FastAPI, db: Database, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeReleases]:
    monkeypatch.setattr(musicbrainz.LIMITER, "interval", 0)
    fake = FakeReleases()
    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    yield fake
    await app.state.discography_sync.wait()
    await app.state.http.aclose()
    app.state.http = real
    async with db.session() as session:
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.EXTERNAL_SERVICES_KEY)
        )
        await session.execute(delete(ArtistInfo))
        await session.commit()


async def test_new_releases(
    app: FastAPI,
    admin: SubsonicUser,
    user: SubsonicUser,
    services: FakeReleases,
    artists: dict[str, str],
) -> None:
    async with signed_in(app, user) as web:
        assert (await web.get("/api/manage/new-releases")).status_code == 403
    async with signed_in(app, admin) as web:
        before = (await web.get("/api/manage/new-releases")).json()
        assert (before["artists"], before["stale"], before["recent"]) == (3, 3, [])

        started = (await web.post("/api/manage/new-releases/sync")).json()
        assert started["running"] is True
        await app.state.discography_sync.wait()

        found = (await web.get("/api/manage/new-releases", params={"months": 6})).json()
        assert (found["sync"]["done"], found["sync"]["total"], found["stale"]) == (3, 3, 0)
        assert [r["title"] for r in found["upcoming"]] == ["Soon"]
        recent = {r["title"]: r for r in found["recent"]}
        assert set(recent) == {"Live Now", "Recent One", "Year Only"}  # owned and old left out
        assert recent["Year Only"]["monthUnknown"] is True
        assert recent["Recent One"]["artistName"] == "Amon Amarth"
        assert [r["title"] for r in found["recent"]][:1] == ["Live Now"]  # newest first
        assert [(c["key"], c["count"]) for c in found["categories"]] == [
            ("album", 3),
            ("album+live", 1),
        ]
        # "Twin" matches two MusicBrainz artists: not linked.
        assert [a["name"] for a in found["unlinked"]] == ["Twin"]

        # Fresh for a day: a new run has nothing to do.
        again = (await web.post("/api/manage/new-releases/sync")).json()
        await app.state.discography_sync.wait()
        assert again["running"] is True
        done = (await web.get("/api/manage/new-releases")).json()["sync"]
        assert (done["running"], done["total"]) == (False, 0)
