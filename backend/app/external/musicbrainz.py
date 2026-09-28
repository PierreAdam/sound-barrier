"""MusicBrainz web service (no key): an artist's discography (release groups), artist
search and lookups.

MusicBrainz allows one request per second per application: every call goes through
`LIMITER`, shared by the whole server (beets, in the import worker, has its own limit).
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.external import ExternalServiceError

API_URL = "https://musicbrainz.org/ws/2"
PAGE_SIZE = 100
MAX_PAGES = 5  # 500 release groups: enough for any real discography
SEARCH_LIMIT = 5

# Display order of the categories (as on the MusicBrainz artist page).
PRIMARY_TYPES = ("album", "single", "ep", "broadcast", "other")

_MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class RateLimiter:
    """At most one request every `interval` seconds."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


LIMITER = RateLimiter(1.0)


@dataclass
class ReleaseGroup:
    mbid: str
    title: str
    primary_type: str | None  # "Album", "EP"... as MusicBrainz writes them
    secondary_types: list[str] = field(default_factory=list[str])  # "Live", "Compilation"...
    first_release_date: str | None = None  # partial ISO date


@dataclass
class ArtistCandidate:
    mbid: str
    name: str
    disambiguation: str | None = None
    country: str | None = None
    type: str | None = None  # "Group", "Person"...
    begin: str | None = None
    end: str | None = None
    score: int = 100  # search relevance (100: best)


def category(primary_type: str | None, secondary_types: list[str]) -> str:
    """The release group's category: primary type then secondary types (sorted),
    lowercase, e.g. "album", "album+live", "ep+demo"; no primary type is "other"."""
    primary = (primary_type or "other").casefold()
    return "+".join([primary, *sorted(s.casefold() for s in secondary_types)])


def parse_mbid(value: str) -> str | None:
    """A MusicBrainz id, alone or in a musicbrainz.org URL."""
    found = _MBID.search(value.strip().casefold())
    return found.group(0) if found else None


async def _get(http: httpx.AsyncClient, path: str, params: dict[str, str]) -> dict[str, Any] | None:
    """The JSON answer, None when MusicBrainz does not know this id (404)."""
    await LIMITER.wait()
    try:
        response = await http.get(f"{API_URL}/{path}", params={**params, "fmt": "json"})
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"MusicBrainz is not reachable: {error}") from error
    if response.status_code in (400, 404):
        return None
    if response.status_code == 503:
        raise ExternalServiceError("MusicBrainz is busy (rate limited), try again later")
    if response.status_code != 200:
        raise ExternalServiceError(f"MusicBrainz error (HTTP {response.status_code})")
    try:
        data: dict[str, Any] = response.json()
    except ValueError as error:
        raise ExternalServiceError("Invalid answer from MusicBrainz") from error
    return data


async def release_groups(http: httpx.AsyncClient, artist_mbid: str) -> list[ReleaseGroup] | None:
    """The artist's release groups, as on the MusicBrainz website (without those made
    only of promotional, bootleg or pseudo releases). None for an unknown artist."""
    groups: list[ReleaseGroup] = []
    for page in range(MAX_PAGES):
        data = await _get(
            http,
            "release-group",
            {
                "artist": artist_mbid,
                "release-group-status": "website-default",
                "limit": str(PAGE_SIZE),
                "offset": str(page * PAGE_SIZE),
            },
        )
        if data is None:
            return None if page == 0 else groups
        found: list[dict[str, Any]] = data.get("release-groups") or []
        for group in found:
            if not isinstance(group.get("id"), str):
                continue
            secondary: list[Any] = group.get("secondary-types") or []
            groups.append(
                ReleaseGroup(
                    mbid=group["id"],
                    title=str(group.get("title") or ""),
                    primary_type=group.get("primary-type") or None,
                    secondary_types=[str(s) for s in secondary],
                    first_release_date=group.get("first-release-date") or None,
                )
            )
        if len(found) < PAGE_SIZE or len(groups) >= int(data.get("release-group-count") or 0):
            break
    return groups


def _candidate(artist: dict[str, Any]) -> ArtistCandidate:
    span: dict[str, Any] = artist.get("life-span") or {}
    return ArtistCandidate(
        mbid=str(artist["id"]),
        name=str(artist.get("name") or ""),
        disambiguation=artist.get("disambiguation") or None,
        country=artist.get("country") or None,
        type=artist.get("type") or None,
        begin=span.get("begin") or None,
        end=span.get("end") or None,
        score=int(artist.get("score") or 100),
    )


async def search_artists(http: httpx.AsyncClient, name: str) -> list[ArtistCandidate]:
    """The best matches for this artist name, most relevant first."""
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    data = await _get(http, "artist", {"query": f'artist:"{escaped}"', "limit": str(SEARCH_LIMIT)})
    artists: list[dict[str, Any]] = (data or {}).get("artists") or []
    return [_candidate(a) for a in artists if isinstance(a.get("id"), str)]


async def lookup_artist(http: httpx.AsyncClient, mbid: str) -> ArtistCandidate | None:
    data = await _get(http, f"artist/{mbid}", {})
    return _candidate(data) if data and isinstance(data.get("id"), str) else None


async def release_group_of(http: httpx.AsyncClient, release_mbid: str) -> str | None:
    """The release group of a release (album tags often only have the release id)."""
    data = await _get(http, f"release/{release_mbid}", {"inc": "release-groups"})
    group: dict[str, Any] = (data or {}).get("release-group") or {}
    return group["id"] if isinstance(group.get("id"), str) else None
