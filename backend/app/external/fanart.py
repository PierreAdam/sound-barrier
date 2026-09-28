"""fanart.tv (personal API key, looked up by MusicBrainz id): artist pictures ("artist
thumbs") and album covers (by release group)."""

from typing import Any

import httpx

from app.external import ExternalServiceError

API_URL = "https://webservice.fanart.tv/v3/music"
KEY_NAME = "fanart"  # in the external services keys
HOSTS = ("fanart.tv",)  # images: assets.fanart.tv
# A known artist to check a key with (Radiohead).
CHECK_MBID = "a74b1b7f-71a5-4011-9441-d0b5e4122711"


class InvalidFanartKeyError(ExternalServiceError):
    pass


async def get(http: httpx.AsyncClient, path: str, key: str) -> dict[str, Any] | None:
    """The JSON answer, None when fanart.tv has nothing for this id."""
    try:
        response = await http.get(f"{API_URL}/{path}", params={"api_key": key})
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"fanart.tv is not reachable: {error}") from error
    if response.status_code in (401, 403):
        raise InvalidFanartKeyError("fanart.tv refused the API key")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ExternalServiceError(f"fanart.tv error (HTTP {response.status_code})")
    try:
        data: dict[str, Any] = response.json()
    except ValueError as error:
        raise ExternalServiceError("Invalid answer from fanart.tv") from error
    return data


def best_images(images: list[dict[str, Any]]) -> list[str]:
    """Image URLs, most liked first."""
    ranked = sorted(images, key=lambda image: -int(image.get("likes") or 0))
    return [str(image["url"]) for image in ranked if isinstance(image.get("url"), str)]


def preview(url: str) -> str:
    """fanart.tv's small version of an image."""
    return url.replace("/fanart/", "/preview/", 1)


async def check_key(http: httpx.AsyncClient, key: str) -> None:
    await get(http, CHECK_MBID, key)
