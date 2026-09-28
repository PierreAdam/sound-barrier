"""Data fetched from external services, cached (see services/artist_info.py)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ArtistInfo(Base):
    """Biography, similar artists and top tracks (Last.fm), picture (a picture provider)
    and discography (MusicBrainz) of an artist. Refreshed after some time; the picture
    file itself is kept in the data folder (`artist-pictures/<artist id>`)."""

    __tablename__ = "artist_info"

    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artist.id", ondelete="CASCADE"), primary_key=True
    )
    # Last.fm (None: not fetched, no API key, or unknown to Last.fm)
    lastfm_url: Mapped[str | None]
    summary: Mapped[str | None]
    biography: Mapped[str | None]
    similar: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # [{name, mbid}]
    top_tracks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # [{title, mbid, playcount}]
    info_fetched_at: Mapped[datetime | None]
    info_error: Mapped[str | None]
    # Picture
    picture_source: Mapped[str | None]  # provider id, None: no picture
    picture_page_url: Mapped[str | None]  # the artist's page at the source (credit)
    picture_content_type: Mapped[str | None]
    picture_fetched_at: Mapped[datetime | None]  # also when none was found
    picture_error: Mapped[str | None]
    # Discography (MusicBrainz, see services/discography.py)
    mbz_artist_id_override: Mapped[str | None]  # chosen by an admin, wins over the tags
    discography_mbid: Mapped[str | None]  # the artist id `discography` was fetched for
    # [{mbid, title, primary_type, secondary_types, first_release_date}]
    discography: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Release id -> its release group id (None: unknown), for albums tagged with a release id.
    release_groups: Mapped[dict[str, str | None]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    discography_fetched_at: Mapped[datetime | None]  # also when the artist was not found
    discography_error: Mapped[str | None]
