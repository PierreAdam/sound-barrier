"""Last.fm web API: artist biographies, similar artists, top tracks and album notes.

Last.fm's user-contributed texts are licensed CC BY-SA: whatever shows them must credit
Last.fm and link to the artist's Last.fm page.
"""

import html
import re
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from app.external import ExternalServiceError

API_URL = "https://ws.audioscrobbler.com/2.0/"
INVALID_KEY = (10, 26)  # invalid API key, suspended API key
NOT_FOUND = 6

_LINK = re.compile(r"<a\s[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class SimilarArtist:
    name: str
    mbid: str | None


@dataclass
class TopTrack:
    title: str
    mbid: str | None  # MusicBrainz recording id
    playcount: int


@dataclass
class LastFmArtist:
    name: str
    url: str | None
    summary: str
    biography: str
    similar: list[SimilarArtist] = field(default_factory=list[SimilarArtist])
    tags: list[str] = field(default_factory=list[str])


@dataclass
class LastFmAlbum:
    url: str | None
    summary: str
    notes: str  # the album's wiki text


class InvalidApiKeyError(ExternalServiceError):
    pass


def plain_text(value: str | None) -> str:
    """Last.fm bios are HTML ending with a "Read more on Last.fm" link: plain text."""
    if not value:
        return ""
    text = _TAG.sub("", _LINK.sub("", value))
    return html.unescape(text).strip()


class LastFm:
    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        self._http = http
        self._key = api_key

    async def _call(self, method: str, **params: str) -> dict[str, Any] | None:
        """The JSON answer, None when Last.fm does not know the artist."""
        query = {"method": method, "api_key": self._key, "format": "json", **params}
        try:
            response = await self._http.get(API_URL, params=query)
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ExternalServiceError(f"Last.fm is not reachable: {error}") from error
        code = data.get("error")
        if code in INVALID_KEY:
            raise InvalidApiKeyError("The Last.fm API key is invalid")
        if code == NOT_FOUND:
            return None
        if code is not None:
            raise ExternalServiceError(f"Last.fm error {code}: {data.get('message', '')}")
        return data

    async def _artist_call(
        self, method: str, name: str, mbid: str | None, **params: str
    ) -> dict[str, Any] | None:
        """By MusicBrainz id when known (exact), else (or if Last.fm does not know the id)
        by name, with Last.fm's spelling corrections."""
        if mbid:
            data = await self._call(method, mbid=mbid, **params)
            if data is not None:
                return data
        return await self._call(method, artist=name, autocorrect="1", **params)

    async def artist(self, name: str, mbid: str | None = None) -> LastFmArtist | None:
        data = await self._artist_call("artist.getInfo", name, mbid)
        artist = _dict(data, "artist")
        if not artist:
            return None
        bio = _dict(artist, "bio")
        return LastFmArtist(
            name=_text(artist, "name") or name,
            url=_text(artist, "url"),
            summary=plain_text(_text(bio, "summary")),
            biography=plain_text(_text(bio, "content")),
            similar=[
                SimilarArtist(_text(s, "name") or "", _text(s, "mbid"))
                for s in _list(_dict(artist, "similar"), "artist")
                if _text(s, "name")
            ],
            tags=[
                t for t in (_text(tag, "name") for tag in _list(_dict(artist, "tags"), "tag")) if t
            ],
        )

    async def top_tracks(
        self, name: str, mbid: str | None = None, limit: int = 50
    ) -> list[TopTrack]:
        data = await self._artist_call("artist.getTopTracks", name, mbid, limit=str(limit))
        tracks = _list(_dict(data, "toptracks"), "track")
        return [
            TopTrack(_text(t, "name") or "", _text(t, "mbid"), int(_text(t, "playcount") or 0))
            for t in tracks
            if _text(t, "name")
        ]

    async def album(self, artist: str, title: str, mbid: str | None = None) -> LastFmAlbum | None:
        """By the release's MusicBrainz id when known, else by artist and title."""
        data = await self._call("album.getInfo", mbid=mbid) if mbid else None
        if data is None:
            data = await self._call("album.getInfo", artist=artist, album=title, autocorrect="1")
        album = _dict(data, "album")
        if not album:
            return None
        wiki = _dict(album, "wiki")
        return LastFmAlbum(
            url=_text(album, "url"),
            summary=plain_text(_text(wiki, "summary")),
            notes=plain_text(_text(wiki, "content")),
        )

    async def check_key(self) -> None:
        """InvalidApiKeyError if Last.fm refuses the key."""
        await self._call("artist.getInfo", artist="Radiohead")


# --- JSON helpers: Last.fm answers are loosely typed ------------------------------------


def _dict(data: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = (data or {}).get(key)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value: Any = data.get(key)
    values: list[Any]
    if isinstance(value, dict):  # a single element is sometimes not wrapped in a list
        values = [value]
    elif isinstance(value, list):
        values = cast(list[Any], value)
    else:
        values = []
    return [cast(dict[str, Any], v) for v in values if isinstance(v, dict)]


def _text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return str(value) if value not in (None, "") else None
