"""Artist pictures from an external source, chosen in Settings.

Each source is a `PictureProvider`; Deezer is the first one (no API key needed). Adding
another (e.g. fanart.tv, which needs an API key and MusicBrainz ids) means one class here,
one entry in PROVIDERS and, if it needs one, an API key in the external services settings.
"""

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.text import normalize, title_key
from app.external import ExternalServiceError, fanart

MAX_PICTURE_BYTES = 8 * 1024 * 1024
NAMESAKES_CHECKED = 5  # same-name artists whose albums are compared with the library


@dataclass
class Picture:
    data: bytes
    content_type: str
    page_url: str | None  # the artist's page at the source (credit link)


class PictureProvider(ABC):
    id: str  # stored in the settings
    label: str  # shown in the UI and in the credit ("Picture: Deezer")
    needs_key: str | None = None  # the external services key it needs (e.g. "fanart")

    @abstractmethod
    async def find(
        self,
        http: httpx.AsyncClient,
        name: str,
        mbid: str | None,
        keys: Mapping[str, str],
        album_titles: Sequence[str] = (),
    ) -> Picture | None:
        """The artist's picture, None if the source has none for this artist.
        `album_titles`: the artist's albums in the library, to tell namesakes apart."""


async def _download(http: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    try:
        response = await http.get(url)
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"Cannot download the picture: {error}") from error
    content_type = response.headers.get("content-type", "").split(";")[0]
    if response.status_code != 200 or not content_type.startswith("image/"):
        return None
    if len(response.content) > MAX_PICTURE_BYTES:
        return None
    return response.content, content_type


def _words(value: str) -> list[str]:
    return normalize(re.sub(r"[^\w\s]", " ", value)).split()


def best_match(name: str, candidates: list[str]) -> int | None:
    """Index of the candidate that is this artist: the same name (ignoring case, accents
    and punctuation), else the first whose name contains it as whole words
    ("Metalocalypse: Dethklok" for "Dethklok"). A merely close name is someone else."""
    wanted = _words(name)
    if not wanted:
        return None
    words = [_words(c) for c in candidates]
    for index, candidate in enumerate(words):
        if candidate == wanted:
            return index
    size = len(wanted)
    for index, candidate in enumerate(words):
        if any(candidate[i : i + size] == wanted for i in range(len(candidate) - size + 1)):
            return index
    return None


class Deezer(PictureProvider):
    id = "deezer"
    label = "Deezer"
    SEARCH_URL = "https://api.deezer.com/search/artist"

    ALBUMS_URL = "https://api.deezer.com/artist/{id}/albums"

    async def _album_titles(self, http: httpx.AsyncClient, artist_id: object) -> set[str]:
        """The artist's album titles on Deezer (matching form); empty if unreachable."""
        try:
            response = await http.get(self.ALBUMS_URL.format(id=artist_id), params={"limit": "100"})
            albums: list[dict[str, Any]] = response.json().get("data") or []
        except (httpx.HTTPError, ValueError):
            return set()
        return {title_key(str(album.get("title") or "")) for album in albums}

    async def _choose(
        self,
        http: httpx.AsyncClient,
        name: str,
        results: list[dict[str, Any]],
        album_titles: Sequence[str],
    ) -> dict[str, Any] | None:
        """The artist among the search results. Several with exactly this name (e.g. many
        "Dope"): the one sharing the most albums with the library, else the most followed."""
        wanted = _words(name)
        namesakes = [r for r in results if _words(str(r.get("name", ""))) == wanted]
        if not namesakes:
            index = best_match(name, [str(r.get("name", "")) for r in results])
            return results[index] if index is not None else None
        namesakes.sort(key=lambda r: -int(r.get("nb_fan") or 0))  # stable: Deezer's order next
        library = {title_key(title) for title in album_titles} - {""}
        if len(namesakes) == 1 or not library:
            return namesakes[0]
        checked = namesakes[:NAMESAKES_CHECKED]
        titles = await asyncio.gather(*(self._album_titles(http, r.get("id")) for r in checked))
        shared = [len(library & found) for found in titles]
        best = max(range(len(checked)), key=lambda i: shared[i])  # first (most fans) on ties
        return checked[best]

    async def find(
        self,
        http: httpx.AsyncClient,
        name: str,
        mbid: str | None,
        keys: Mapping[str, str],
        album_titles: Sequence[str] = (),
    ) -> Picture | None:
        try:
            response = await http.get(self.SEARCH_URL, params={"q": name, "limit": "10"})
            results: list[dict[str, Any]] = response.json().get("data") or []
        except (httpx.HTTPError, ValueError) as error:
            raise ExternalServiceError(f"Deezer is not reachable: {error}") from error
        match = await self._choose(http, name, results, album_titles)
        if match is None:
            return None
        url = match.get("picture_xl") or match.get("picture_big")
        # Artists without a picture get a generic silhouette: ".../images/artist//...".
        if not isinstance(url, str) or "/artist//" in url:
            return None
        found = await _download(http, url)
        if found is None:
            return None
        link = match.get("link")
        return Picture(found[0], found[1], link if isinstance(link, str) else None)


class FanartTv(PictureProvider):
    """Needs the artist's MusicBrainz id (from the tags, e.g. written by beets)."""

    id = "fanarttv"
    label = "fanart.tv"
    needs_key = fanart.KEY_NAME

    async def find(
        self,
        http: httpx.AsyncClient,
        name: str,
        mbid: str | None,
        keys: Mapping[str, str],
        album_titles: Sequence[str] = (),
    ) -> Picture | None:
        key = keys.get(fanart.KEY_NAME)
        if not mbid or not key:
            return None
        data = await fanart.get(http, mbid, key)
        thumbs: list[dict[str, Any]] = (data or {}).get("artistthumb") or []
        for url in fanart.best_images(thumbs):
            found = await _download(http, url)
            if found is not None:
                return Picture(found[0], found[1], f"https://fanart.tv/artist/{mbid}")
        return None


PROVIDERS: dict[str, PictureProvider] = {p.id: p for p in (Deezer(), FanartTv())}
