"""Tag editor (admins): an album's tags, written into its files, then rescanned."""

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import AdminCaller, ApiModel, DbSession
from app.library_manager.imports import ImportManager
from app.library_manager.tag_files import TagChange, TagWriteError
from app.models import Album, AlbumGenre, Genre, MusicFolder, Song
from app.services.scans import ScanManager

router = APIRouter(tags=["tags"])


class TrackTags(ApiModel):
    id: uuid.UUID
    path: str = ""  # read only (relative to the library folder)
    disc: int | None = Field(default=None, ge=0, le=999)
    track: int | None = Field(default=None, ge=0, le=9999)
    title: str
    artist: str | None = None


class AlbumTags(ApiModel):
    album: str
    album_artist: str | None = None
    year: int | None = Field(default=None, ge=0, le=9999)
    genre: str | None = None
    compilation: bool = False
    tracks: list[TrackTags]


class SavedTags(ApiModel):
    album_id: uuid.UUID | None  # an edited album can become another one (new name / artist)
    files: int  # files rewritten


async def _load(session: DbSession, album_id: uuid.UUID) -> tuple[Album, list[Song], str | None]:
    album = await session.get(Album, album_id)
    if album is None or album.missing_since is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown album")
    songs = list(
        (
            await session.scalars(
                select(Song)
                .where(Song.album_id == album_id, Song.missing_since.is_(None))
                .order_by(
                    func.coalesce(Song.disc_number, 0),
                    func.coalesce(Song.track_number, 0),
                    Song.path,
                )
            )
        ).all()
    )
    genre = await session.scalar(
        select(Genre.name)
        .join(AlbumGenre, AlbumGenre.genre_id == Genre.id)
        .where(AlbumGenre.album_id == album_id)
        .order_by(AlbumGenre.position)
        .limit(1)
    )
    return album, songs, genre


@router.get("/albums/{album_id}/tags")
async def get_tags(album_id: uuid.UUID, _: AdminCaller, session: DbSession) -> AlbumTags:
    album, songs, genre = await _load(session, album_id)
    return AlbumTags(
        album=album.name,
        album_artist=album.display_artist,
        year=album.year,
        genre=genre,
        compilation=album.is_compilation,
        tracks=[
            TrackTags(
                id=s.id,
                path=s.path,
                disc=s.disc_number,
                track=s.track_number,
                title=s.title,
                artist=s.display_artist,
            )
            for s in songs
        ],
    )


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.put("/albums/{album_id}/tags")
async def save_tags(
    album_id: uuid.UUID, body: AlbumTags, request: Request, _: AdminCaller, session: DbSession
) -> SavedTags:
    """Writes the changed fields only (unchanged tags, e.g. multi-valued artists, stay as
    they are). Files known to beets are written through beets."""
    album, songs, genre = await _load(session, album_id)
    folder = await session.get(MusicFolder, songs[0].music_folder_id) if songs else None
    if folder is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This album has no file")
    if not _clean(body.album):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The album needs a title")
    root = Path(folder.path)
    album_fields: dict[str, Any] = {}
    if _clean(body.album) != album.name:
        album_fields["album"] = _clean(body.album)
    if _clean(body.album_artist) != album.display_artist:
        album_fields["albumartist"] = _clean(body.album_artist)
    if body.year != album.year:
        album_fields["year"] = body.year
    if _clean(body.genre) != genre:
        album_fields["genre"] = _clean(body.genre)
    if body.compilation != album.is_compilation:
        album_fields["comp"] = body.compilation

    edited = {t.id: t for t in body.tracks}
    changes: list[TagChange] = []
    for song in songs:
        fields = dict(album_fields)
        track = edited.get(song.id)
        if track is not None:
            if not _clean(track.title):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Every track needs a title")
            if _clean(track.title) != song.title:
                fields["title"] = _clean(track.title)
            if _clean(track.artist) != song.display_artist:
                fields["artist"] = _clean(track.artist)
            if track.track != song.track_number:
                fields["track"] = track.track
            if track.disc != song.disc_number:
                fields["disc"] = track.disc
        if fields:
            changes.append(TagChange(root / song.path, fields))
    if not changes:
        return SavedTags(album_id=album_id, files=0)

    first_song = songs[0].id  # the album of this song afterwards is the edited album
    imports: ImportManager = request.app.state.imports
    try:
        await imports.call_tagger(imports.tagger.write_tags, changes, root)
    except (TagWriteError, ValueError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    # The library (web UI, Subsonic apps) shows the new tags as soon as this returns.
    scans: ScanManager = request.app.state.scans
    folders = sorted({str(Path(s.path).parent.as_posix()) for s in songs})
    await scans.scan_paths(folder.id, [f if f != "." else "" for f in folders])
    session.expire_all()
    new_album = await session.scalar(select(Song.album_id).where(Song.id == first_song))
    return SavedTags(album_id=new_album, files=len(changes))
