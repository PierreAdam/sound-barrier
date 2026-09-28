import uuid
from datetime import date

from app.external import musicbrainz
from app.external.musicbrainz import ReleaseGroup
from app.models import Album
from app.services import discography
from app.services.browsing import AlbumEntry


def test_category_is_the_type_combination() -> None:
    assert musicbrainz.category("Album", []) == "album"
    assert musicbrainz.category("Album", ["Live", "Compilation"]) == "album+compilation+live"
    assert musicbrainz.category(None, ["Demo"]) == "other+demo"


def test_parse_mbid() -> None:
    mbid = "d4f8c0a2-2c83-4a5e-9f3b-6b3b1f0c2a11"
    assert musicbrainz.parse_mbid(mbid.upper()) == mbid
    assert musicbrainz.parse_mbid(f"https://musicbrainz.org/artist/{mbid}/releases") == mbid
    assert musicbrainz.parse_mbid("Amon Amarth") is None


def test_title_matches_prefer_plain_albums() -> None:
    # A single named like the album: the owned album is the album.
    groups = [
        ReleaseGroup("s", "Berserker", "Single", [], "2019-03-01"),
        ReleaseGroup("a", "Berserker", "Album", [], "2019-05-03"),
    ]

    album = Album(id=uuid.uuid4(), name="Berserker (Deluxe)", artwork_id=None)
    entry = AlbumEntry(album, song_count=1, duration_ms=0, starred_at=None, rating=None)
    categories, entries = discography.match(groups, [entry], {}, date(2026, 1, 1))
    assert [(e.group.mbid, e.owned is not None) for e in entries] == [("a", True), ("s", False)]
    assert [c.key for c in categories] == ["album", "single"]
