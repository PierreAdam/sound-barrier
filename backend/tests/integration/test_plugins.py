"""Plugins: settings (admins) and the "Search links" plugin, with the sites and
MusicBrainz replaced by a fake transport."""

import io
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import delete

from app.core.db import Database
from app.external import musicbrainz
from app.models import ArtistInfo, ServerSetting
from app.plugins.search_links import icons
from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_discography import LIVE, FakeServices, artists

pytestmark = pytest.mark.integration

__all__ = ["artists"]  # fixture

PRIVATE_HOST = "intranet.example"


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), (20, 200, 20)).save(output, format="PNG")
    return output.getvalue()


class FakeSites(FakeServices):
    """MusicBrainz as in test_discography, plus a store and the default sites."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "store.example":
            self.requests.append(request)
            if url.path == "/":
                page = '<html><head><link rel="icon" href="/static/icon.png"></head></html>'
                return httpx.Response(200, text=page, headers={"content-type": "text/html"})
            if url.path == "/static/icon.png":
                return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
            return httpx.Response(404)
        if url.host in ("duckduckgo.com", "www.amazon.fr", "www.fnac.com", PRIVATE_HOST):
            self.requests.append(request)
            return httpx.Response(404)
        return super().handle(request)


@pytest.fixture
async def sites(
    app: FastAPI, db: Database, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeSites]:
    monkeypatch.setattr(musicbrainz.LIMITER, "interval", 0)

    async def resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.5"] if host == PRIVATE_HOST else ["93.184.216.34"]

    monkeypatch.setattr(icons, "resolve", resolve)
    fake = FakeSites()
    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    yield fake
    await app.state.http.aclose()
    app.state.http = real
    async with db.session() as session:
        await session.execute(delete(ServerSetting).where(ServerSetting.key.like("plugin:%")))
        await session.execute(delete(ArtistInfo))
        await session.commit()


STORE = {
    "name": "My store",
    "method": "POST",
    "url": "https://store.example/search",
    "body": "SearchForm%5Bn%5D={query}&go-search=Search",
}


async def test_plugin_settings(
    app: FastAPI, admin: SubsonicUser, user: SubsonicUser, sites: FakeSites, tmp_path: Path
) -> None:
    async with signed_in(app, user) as web:
        assert (await web.get("/api/plugins")).status_code == 403
    async with signed_in(app, admin) as web:
        [plugin] = (await web.get("/api/plugins")).json()
        assert (plugin["id"], plugin["enabled"], plugin["capabilities"]) == (
            "search-links",
            True,
            ["links"],
        )
        [sites_field] = plugin["fields"]
        assert (sites_field["type"], sites_field["canTry"]) == ("list", True)
        body_field = next(f for f in sites_field["fields"] if f["key"] == "body")
        assert body_field["visibleWhen"] == ["method", "POST"]
        assert [s["name"] for s in plugin["settings"]["sites"]] == [
            "DuckDuckGo",
            "Amazon.fr",
            "Fnac",
        ]

        refused = await web.put(
            "/api/plugins/search-links",
            json={"enabled": True, "settings": {"sites": [{**STORE, "body": "q={title}"}]}},
        )
        assert refused.status_code == 400
        assert "{title}" in refused.json()["detail"]

        # The store first, then DuckDuckGo; the default ones never got an icon (404).
        store_and_ddg = [STORE, plugin["settings"]["sites"][0]]
        saved = await web.put(
            "/api/plugins/search-links",
            json={"enabled": True, "settings": {"sites": store_and_ddg}},
        )
        assert saved.status_code == 200, saved.text
        stored = saved.json()["plugin"]["settings"]["sites"]
        assert [s["name"] for s in stored] == ["My store", "DuckDuckGo"]
        assert stored[0]["id"]  # given by the plugin
        assert saved.json()["warnings"] == [
            "No icon for “DuckDuckGo”: HTTP 404 for https://duckduckgo.com/favicon.ico"
        ]

        icon = await web.get(f"/api/plugins/search-links/assets/icons/{stored[0]['id']}")
        assert icon.status_code == 200
        assert icon.headers["content-type"] == "image/png"
        missing = await web.get("/api/plugins/search-links/assets/icons/duckduckgo")
        assert missing.status_code == 404

        # Try: one row, saved or not, for the sample album.
        tried = await web.post(
            "/api/plugins/search-links/try",
            json={"settings": {"sites": stored}, "field": "sites", "item": 0},
        )
        [link] = tried.json()
        assert link["method"] == "POST"
        assert link["form"] == [["SearchForm[n]", "Amon Amarth Berserker"], ["go-search", "Search"]]


async def test_icons_are_not_fetched_from_private_addresses(
    app: FastAPI, admin: SubsonicUser, sites: FakeSites
) -> None:
    site = {"name": "Intranet", "url": f"https://{PRIVATE_HOST}/?q={{query}}"}
    async with signed_in(app, admin) as web:
        saved = await web.put(
            "/api/plugins/search-links", json={"enabled": True, "settings": {"sites": [site]}}
        )
    assert "local or private address" in saved.json()["warnings"][0]
    assert sites.count(PRIVATE_HOST) == 0


async def test_links_of_a_missing_album(
    app: FastAPI,
    admin: SubsonicUser,
    user: SubsonicUser,
    sites: FakeSites,
    artists: dict[str, str],
) -> None:
    amon = artists["Amon Amarth"]
    async with signed_in(app, admin) as web:
        await web.get(f"/api/artists/{amon}/discography")
        await web.put(
            "/api/plugins/search-links",
            json={
                "enabled": True,
                "settings": {"sites": [STORE, {**STORE, "name": "Off", "enabled": False}]},
            },
        )
        [found] = (await web.get(f"/api/artists/{amon}/discography/{LIVE}/links")).json()
        assert (found["plugin"], found["name"]) == ("search-links", "Search links")
        [link] = found["links"]
        assert link["label"] == "My store"
        assert link["form"][0] == ["SearchForm[n]", "Amon Amarth Wrath of the Norsemen"]
        assert link["iconUrl"].startswith("/api/plugins/search-links/assets/icons/")
        unknown = await web.get(f"/api/artists/{amon}/discography/not-a-group/links")
        assert unknown.status_code == 404

        # The plugin turned off: no links.
        await web.put(
            "/api/plugins/search-links", json={"enabled": False, "settings": {"sites": [STORE]}}
        )
        assert (await web.get(f"/api/artists/{amon}/discography/{LIVE}/links")).json() == []
    async with signed_in(app, user) as web:
        forbidden = await web.get(f"/api/artists/{amon}/discography/{LIVE}/links")
        assert forbidden.status_code == 403
