"""Album cover search (admins choosing a cover), from several possible sources.

Each source is a `CoverProvider`; Deezer is the first one. Downloads are only allowed from
the hosts a provider declares (`hosts`): the web UI sends back image URLs, which must not
make the server fetch anything else.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.external import ExternalServiceError, fanart

MAX_IMAGE_BYTES = 15 * 1024 * 1024


@dataclass
class CoverResult:
    source: str  # provider id
    title: str
    artist: str
    image_url: str  # the largest image
    thumbnail_url: str
    width: int | None = None
    height: int | None = None
    page_url: str | None = None  # the album's page at the source


@dataclass
class CoverContext:
    """What a source may use besides the text query."""

    release_group_id: str | None = None  # MusicBrainz, from the album's tags
    keys: Mapping[str, str] = field(default_factory=dict[str, str])  # external services


class CoverProvider(ABC):
    id: str
    label: str
    hosts: tuple[str, ...]  # images may be downloaded from these hosts (and sub-domains)

    @abstractmethod
    async def search(
        self, http: httpx.AsyncClient, query: str, context: CoverContext
    ) -> list[CoverResult]: ...

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return parts.scheme == "https" and any(
            host == allowed or host.endswith(f".{allowed}") for allowed in self.hosts
        )


class DeezerCovers(CoverProvider):
    id = "deezer"
    label = "Deezer"
    hosts = ("dzcdn.net",)
    SEARCH_URL = "https://api.deezer.com/search/album"

    async def search(
        self, http: httpx.AsyncClient, query: str, context: CoverContext
    ) -> list[CoverResult]:
        try:
            response = await http.get(self.SEARCH_URL, params={"q": query, "limit": "25"})
            albums: list[dict[str, Any]] = response.json().get("data") or []
        except (httpx.HTTPError, ValueError) as error:
            raise ExternalServiceError(f"Deezer is not reachable: {error}") from error
        results: list[CoverResult] = []
        for album in albums:
            image = album.get("cover_xl")
            thumbnail = album.get("cover_medium") or image
            # Albums without a cover get a placeholder: ".../images/cover//...".
            if not isinstance(image, str) or "/cover//" in image or not isinstance(thumbnail, str):
                continue
            artist: dict[str, Any] = album.get("artist") or {}
            link = album.get("link")
            results.append(
                CoverResult(
                    source=self.id,
                    title=str(album.get("title") or ""),
                    artist=str(artist.get("name") or ""),
                    image_url=image,
                    thumbnail_url=thumbnail,
                    width=1000,  # Deezer's "xl" covers
                    height=1000,
                    page_url=link if isinstance(link, str) else None,
                )
            )
        return results


class FanartCovers(CoverProvider):
    """The album's covers on fanart.tv: only with a MusicBrainz release group id (in the
    tags) and a fanart.tv key; the text query is not used."""

    id = "fanarttv"
    label = "fanart.tv"
    hosts = fanart.HOSTS

    async def search(
        self, http: httpx.AsyncClient, query: str, context: CoverContext
    ) -> list[CoverResult]:
        key = context.keys.get(fanart.KEY_NAME)
        group = context.release_group_id
        if not key or not group:
            return []
        data = await fanart.get(http, f"albums/{group}", key)
        albums: dict[str, Any] = (data or {}).get("albums") or {}
        album: dict[str, Any] = albums.get(group) or {}
        covers: list[dict[str, Any]] = album.get("albumcover") or []
        name = str((data or {}).get("name") or "")
        return [
            CoverResult(
                source=self.id,
                title=query,
                artist=name,
                image_url=url,
                thumbnail_url=fanart.preview(url),
                width=1000,  # fanart.tv album covers are 1000 x 1000
                height=1000,
                page_url=None,
            )
            for url in fanart.best_images(covers)
        ]


COVER_PROVIDERS: dict[str, CoverProvider] = {p.id: p for p in (DeezerCovers(), FanartCovers())}


def provider_for(url: str) -> CoverProvider | None:
    """The provider this image URL may be downloaded for, if any."""
    return next((p for p in COVER_PROVIDERS.values() if p.allows(url)), None)


async def download(http: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    """An image from an allowed host (ExternalServiceError otherwise)."""
    if provider_for(url) is None:
        raise ExternalServiceError("This image does not come from a known cover source")
    try:
        response = await http.get(url)
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"Cannot download the image: {error}") from error
    content_type = response.headers.get("content-type", "").split(";")[0]
    if response.status_code != 200 or not content_type.startswith("image/"):
        raise ExternalServiceError(f"Not an image (HTTP {response.status_code})")
    if len(response.content) > MAX_IMAGE_BYTES:
        raise ExternalServiceError("The image is too large")
    return response.content, content_type
