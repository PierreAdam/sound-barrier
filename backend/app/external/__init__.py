"""Clients of external services (Last.fm, picture providers). Only artist names and
MusicBrainz ids are sent; nothing about the users."""

import httpx

from app import __version__

USER_AGENT = f"Sound-Barrier/{__version__} (self-hosted music server)"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ExternalServiceError(Exception):
    """The service could not be reached or refused the request (shown to admins)."""


def create_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )
