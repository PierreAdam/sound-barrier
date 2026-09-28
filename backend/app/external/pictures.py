"""Artist pictures from an external source, chosen in Settings.

Each source is a `PictureProvider`; Deezer is the first one (no API key needed). Adding
another (e.g. fanart.tv, which needs an API key and MusicBrainz ids) means one class here,
one entry in PROVIDERS and, if it needs one, an API key in the external services settings.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.text import normalize
from app.external import ExternalServiceError, fanart

MAX_PICTURE_BYTES = 8 * 1024 * 1024


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
        self, http: httpx.AsyncClient, name: str, mbid: str | None, keys: Mapping[str, str]
    ) -> Picture | None:
        """The artist's picture, None if the source has none for this artist."""


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

    async def find(
        self, http: httpx.AsyncClient, name: str, mbid: str | None, keys: Mapping[str, str]
    ) -> Picture | None:
        try:
            response = await http.get(self.SEARCH_URL, params={"q": name, "limit": "10"})
            results: list[dict[str, Any]] = response.json().get("data") or []
        except (httpx.HTTPError, ValueError) as error:
            raise ExternalServiceError(f"Deezer is not reachable: {error}") from error
        index = best_match(name, [str(r.get("name", "")) for r in results])
        if index is None:
            return None
        match = results[index]
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
        self, http: httpx.AsyncClient, name: str, mbid: str | None, keys: Mapping[str, str]
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
