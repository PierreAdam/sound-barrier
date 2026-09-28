"""Clients of external services (Last.fm, MusicBrainz, picture providers). Only artist
names, album titles and MusicBrainz ids are sent; nothing about the users."""

import httpx

from app import __version__

# MusicBrainz asks for a way to contact the application's authors.
PROJECT_URL = "https://github.com/PierreAdam/sound-barrier"
USER_AGENT = f"Sound-Barrier/{__version__} (+{PROJECT_URL})"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ExternalServiceError(Exception):
    """The service could not be reached or refused the request (shown to admins)."""


def create_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )
