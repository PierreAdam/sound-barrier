"""Service results -> Subsonic response models."""

from app.models import Directory
from app.services.browsing import AlbumEntry, ArtistEntry, NamedRef, SongEntry
from app.subsonic import schemas

# OpenSubsonic mediaType of a song, from the kind of its library folder.
_MEDIA_TYPES = {"podcasts": "podcast", "audiobooks": "audiobook"}


def _ref(ref: NamedRef) -> schemas.ArtistRef:
    return schemas.ArtistRef(id=str(ref.id), name=ref.name)


def _seconds(ms: int) -> int:
    return round(ms / 1000)


def item_date(value: str | None) -> schemas.ItemDate | None:
    """Partial ISO date ("2009", "2009-11", "2009-11-23") -> OpenSubsonic ItemDate."""
    if not value:
        return None
    parts = [int(p) for p in value.split("-")[:3]]
    return schemas.ItemDate(
        year=parts[0],
        month=parts[1] if len(parts) > 1 else None,
        day=parts[2] if len(parts) > 2 else None,
    )


def artist(entry: ArtistEntry) -> schemas.ArtistID3:
    a = entry.artist
    return schemas.ArtistID3(
        id=str(a.id),
        name=a.name,
        # The artist id itself: getCoverArt resolves it to the artist image or an album cover.
        cover_art=str(a.id),
        album_count=entry.album_count,
        starred=entry.starred_at,
        user_rating=entry.rating,
        music_brainz_id=a.mbz_artist_id,
        sort_name=a.sort_name,
    )


def album(entry: AlbumEntry) -> schemas.AlbumID3:
    a = entry.album
    return schemas.AlbumID3(
        id=str(a.id),
        name=a.name,
        artist=a.display_artist,
        artist_id=str(a.artist_id),
        cover_art=str(a.artwork_id) if a.artwork_id else None,
        song_count=entry.song_count,
        duration=_seconds(entry.duration_ms),
        created=a.created_at,
        starred=entry.starred_at,
        year=a.year,
        genre=entry.genres[0] if entry.genres else None,
        user_rating=entry.rating,
        play_count=entry.play_count,
        played=entry.played,
        record_labels=[schemas.RecordLabel(name=label) for label in a.record_labels],
        music_brainz_id=a.mbz_album_id,
        genres=[schemas.ItemGenre(name=g) for g in entry.genres],
        artists=[_ref(r) for r in entry.artists],
        display_artist=a.display_artist,
        release_types=a.release_types,
        moods=a.moods,
        sort_name=a.sort_name,
        original_release_date=item_date(a.original_release_date),
        release_date=item_date(a.release_date),
        is_compilation=a.is_compilation,
        explicit_status=a.explicit_status,
        disc_titles=[
            schemas.DiscTitle(disc=int(d["disc"]), title=str(d["title"])) for d in a.disc_titles
        ],
    )


def song(entry: SongEntry) -> schemas.Child:
    s, al = entry.song, entry.album
    artwork = al.artwork_id or s.artwork_id  # album cover first: one image cached per album
    replay_gain = None
    if any(
        v is not None
        for v in (
            s.replaygain_track_gain,
            s.replaygain_album_gain,
            s.replaygain_track_peak,
            s.replaygain_album_peak,
        )
    ):
        replay_gain = schemas.ReplayGain(
            track_gain=s.replaygain_track_gain,
            album_gain=s.replaygain_album_gain,
            track_peak=s.replaygain_track_peak,
            album_peak=s.replaygain_album_peak,
        )
    contributors = [
        schemas.Contributor(role=r.role, sub_role=r.sub_role or None, artist=_ref(r.artist))
        for r in entry.roles
        if r.role not in ("artist", "albumartist")
    ]
    return schemas.Child(
        id=str(s.id),
        parent=str(s.directory_id),
        title=s.title,
        album=al.name,
        artist=s.display_artist,
        track=s.track_number,
        year=s.year,
        genre=entry.genres[0] if entry.genres else None,
        cover_art=str(artwork) if artwork else None,
        size=s.size,
        content_type=s.content_type,
        suffix=s.suffix,
        duration=_seconds(s.duration_ms),
        bit_rate=s.bit_rate,
        path=s.path,
        disc_number=s.disc_number,
        created=s.created_at,
        album_id=str(s.album_id),
        artist_id=str(s.artist_id),
        starred=entry.starred_at,
        user_rating=entry.rating,
        play_count=entry.play_count,
        played=entry.last_played_at,
        media_type=_MEDIA_TYPES.get(entry.folder_kind, "song"),
        bookmark_position=entry.bookmark_ms,
        bit_depth=s.bit_depth,
        sampling_rate=s.sample_rate,
        channel_count=s.channels,
        music_brainz_id=s.mbz_recording_id,
        genres=[schemas.ItemGenre(name=g) for g in entry.genres],
        artists=[_ref(r) for r in entry.artists("artist")],
        display_artist=s.display_artist,
        album_artists=[_ref(r) for r in entry.artists("albumartist")],
        display_album_artist=al.display_artist,
        contributors=contributors,
        display_composer=s.display_composer,
        bpm=s.bpm,
        comment=s.comment,
        sort_name=s.sort_title,
        explicit_status=s.explicit_status,
        replay_gain=replay_gain,
    )


# --- folder browsing ---------------------------------------------------------


def index_artist(directory: Directory) -> schemas.Artist:
    return schemas.Artist(id=str(directory.id), name=directory.name)


def folder(directory: Directory, album: AlbumEntry | None = None) -> schemas.Child:
    """A directory as a `Child` (isDir): with the album's details when it holds one."""
    if album is None:
        return schemas.Child(
            id=str(directory.id),
            parent=str(directory.parent_id) if directory.parent_id else None,
            is_dir=True,
            title=directory.name,
            cover_art=str(directory.artwork_id) if directory.artwork_id else None,
            created=directory.created_at,
            media_type="artist",
        )
    a = album.album
    return schemas.Child(
        id=str(directory.id),
        parent=str(directory.parent_id) if directory.parent_id else None,
        is_dir=True,
        title=a.name,
        album=a.name,
        artist=a.display_artist,
        year=a.year,
        genre=album.genres[0] if album.genres else None,
        cover_art=str(a.artwork_id) if a.artwork_id else None,
        duration=_seconds(album.duration_ms),
        created=a.created_at,
        album_id=str(a.id),
        artist_id=str(a.artist_id),
        starred=album.starred_at,
        user_rating=album.rating,
        play_count=album.play_count,
        played=album.played,
        media_type="album",
    )
