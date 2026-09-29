"""Per-user preferences of the web UI, stored with the user (`app_user.preferences`).

Only what should follow the user from one device to another lives here (theme, player
crossfade, categories of "Missing albums"); per-device settings (volume, shuffle...) stay
in the browser.
"""

import logging
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser

logger = logging.getLogger(__name__)

MAX_CROSSFADE_SECONDS = 12
_ACCENT = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_CATEGORY = re.compile(r"^[a-z][a-z0-9 +/-]{0,119}$")  # e.g. "album+live", "mixtape/street"


class _Model(BaseModel):
    # camelCase on the wire (web UI), snake_case in the database.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class ThemePreferences(_Model):
    mode: Literal["dark", "light", "system"] = "dark"
    # A palette name of the web UI (theme.less); unknown ones fall back to the default.
    accent: str = "teal"

    @field_validator("accent")
    @classmethod
    def _check_accent(cls, value: str) -> str:
        if not _ACCENT.match(value):
            raise ValueError("accent must be a short lowercase name")
        return value


class PlayerPreferences(_Model):
    crossfade: bool = False
    crossfade_seconds: Annotated[float, Field(ge=1, le=MAX_CROSSFADE_SECONDS)] = 5


def _default_categories() -> list[str]:
    return ["album"]


class DiscographyPreferences(_Model):
    # Release group categories shown in "Missing albums" (musicbrainz.category), for all
    # artists: only plain albums unless the user chooses more.
    categories: Annotated[list[str], Field(max_length=100)] = Field(
        default_factory=_default_categories
    )
    # New releases (Library Management): the last N months.
    recent_months: Annotated[int, Field(ge=1, le=12)] = 6

    @field_validator("categories")
    @classmethod
    def _check_categories(cls, value: list[str]) -> list[str]:
        if any(not _CATEGORY.match(c) for c in value):
            raise ValueError("categories must be MusicBrainz release group types")
        return sorted(set(value))


class Preferences(_Model):
    theme: ThemePreferences = Field(default_factory=ThemePreferences)
    player: PlayerPreferences = Field(default_factory=PlayerPreferences)
    discography: DiscographyPreferences = Field(default_factory=DiscographyPreferences)


def get(user: AppUser) -> Preferences:
    """The user's preferences; missing or invalid stored values get their default."""
    stored: dict[str, Any] = user.preferences or {}
    try:
        return Preferences.model_validate(stored)
    except ValidationError:
        logger.warning("Invalid preferences stored for %s, using defaults", user.username)
        return Preferences()


async def save(session: AsyncSession, user: AppUser, preferences: Preferences) -> Preferences:
    user.preferences = preferences.model_dump()
    await session.flush()
    return preferences
