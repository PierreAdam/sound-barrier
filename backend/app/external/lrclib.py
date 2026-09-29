"""LRCLIB (lrclib.net): a free, open database of song lyrics, many of them synced (LRC).
No key; a meaningful User-Agent is asked for (ours, see app.external)."""

from dataclasses import dataclass
from typing import Any, cast

import httpx

from app.external import ExternalServiceError

API_URL = "https://lrclib.net/api"
DURATION_TOLERANCE_S = 3  # a search result must last about as long as the song


@dataclass
class LrclibLyrics:
    synced: str | None  # LRC text
    plain: str | None
    instrumental: bool


def _lyrics(data: dict[str, Any]) -> LrclibLyrics:
    return LrclibLyrics(
        synced=data.get("syncedLyrics") or None,
        plain=data.get("plainLyrics") or None,
        instrumental=bool(data.get("instrumental")),
    )


async def _get(http: httpx.AsyncClient, path: str, params: dict[str, str]) -> Any:
    try:
        response = await http.get(f"{API_URL}/{path}", params=params)
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"LRCLIB is not reachable: {error}") from error
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ExternalServiceError(f"LRCLIB error (HTTP {response.status_code})")
    try:
        return response.json()
    except ValueError as error:
        raise ExternalServiceError("Invalid answer from LRCLIB") from error


async def find(
    http: httpx.AsyncClient, artist: str, title: str, album: str, duration_s: int
) -> LrclibLyrics | None:
    """The song's lyrics: the exact entry (artist, title, album, duration), else the best
    search result of about the same duration (synced ones first)."""
    try:
        exact = await _get(
            http,
            "get",
            {
                "artist_name": artist,
                "track_name": title,
                "album_name": album,
                "duration": str(duration_s),
            },
        )
    except ExternalServiceError:
        exact = None  # this one may be busy (it asks other sites): the search may answer
    if isinstance(exact, dict):
        return _lyrics(cast(dict[str, Any], exact))
    results = await _get(http, "search", {"artist_name": artist, "track_name": title})
    entries = cast(list[Any], results) if isinstance(results, list) else []
    candidates = [
        entry
        for entry in (cast(dict[str, Any], r) for r in entries if isinstance(r, dict))
        if abs(float(entry.get("duration") or 0) - duration_s) <= DURATION_TOLERANCE_S
    ]
    candidates.sort(key=lambda entry: not entry.get("syncedLyrics"))
    return _lyrics(candidates[0]) if candidates else None
