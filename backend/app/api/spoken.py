"""Podcasts and audiobooks pages of the web UI (services/spoken.py), and their details
(admins can change them, services/spoken_details.py)."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field

from app.api.deps import AdminCaller, ApiModel, CurrentCaller, DbSession
from app.api.songs import web_song
from app.external import ExternalServiceError, books
from app.services import (
    bookmarks,
    browsing,
    music_folders,
    server_settings,
    spoken,
    spoken_details,
)
from app.services.scans import ScanManager

router = APIRouter(prefix="/spoken", tags=["podcasts and audiobooks"])


class ShowOut(ApiModel):
    id: uuid.UUID
    kind: str  # podcasts, audiobooks
    title: str
    author: str
    cover_art: str | None
    episodes: int
    duration_ms: int
    latest: datetime | None  # the newest episode's file date
    started: int  # episodes / chapters with a bookmark
    played: int  # listened to (played, no bookmark left)
    year: int | None
    narrator: str | None  # audiobooks
    series: str | None  # audiobooks: the series, and the book's number in it
    series_number: str | None


class ResumeOut(ApiModel):
    show: ShowOut
    episode: dict[str, Any]  # Child, with bookmarkPosition
    changed_at: datetime


class SpokenPageOut(ApiModel):
    continue_listening: list[ResumeOut]
    shows: list[ShowOut]


class ShowPageOut(ApiModel):
    show: ShowOut
    episodes: list[dict[str, Any]]  # Child, in listening order
    description: str | None
    genre: str | None


def _show(show: spoken.Show) -> ShowOut:
    album = show.album
    return ShowOut(
        id=album.id,
        kind=show.kind,
        title=album.name,
        author=album.display_artist,
        cover_art=str(album.artwork_id) if album.artwork_id else None,
        episodes=len(show.episodes),
        duration_ms=show.duration_ms,
        latest=show.latest,
        started=sum(1 for e in show.episodes if e.bookmark_ms is not None),
        played=sum(1 for e in show.episodes if e.play_count and e.bookmark_ms is None),
        year=album.year,
        narrator=album.narrator,
        series=album.series,
        series_number=album.series_number,
    )


@router.get("/{kind}")
async def spoken_page(kind: str, caller: CurrentCaller, session: DbSession) -> SpokenPageOut:
    """Continue listening, then every show / book of a kind (podcasts, audiobooks)."""
    if kind not in music_folders.SPOKEN_KINDS or not await browsing.spoken_folder_ids(
        session, caller.user, kind
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available")
    resumes = await spoken.continue_listening(session, caller.user, (kind,))
    found = await spoken.shows(session, caller.user, (kind,))
    return SpokenPageOut(
        continue_listening=[
            ResumeOut(
                show=_show(r.show),
                episode=web_song(r.episode, spoken.book_places(r.show).get(r.episode.song.id)),
                changed_at=r.changed_at,
            )
            for r in resumes
        ],
        shows=[_show(s) for s in found],
    )


@router.get("/shows/{album_id}")
async def show_page(album_id: uuid.UUID, caller: CurrentCaller, session: DbSession) -> ShowPageOut:
    found = await spoken.show(session, caller.user, album_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown show or book")
    places = spoken.book_places(found)
    return ShowPageOut(
        show=_show(found),
        episodes=[web_song(e, places.get(e.song.id)) for e in found.episodes],
        description=found.album.description,
        genre=await spoken_details.genre_of(session, album_id),
    )


class ChapterModel(ApiModel):
    start_ms: int = Field(ge=0)
    title: str = Field(max_length=500)


class FileModel(ApiModel):
    id: uuid.UUID
    title: str = Field(max_length=500)
    chapters: list[ChapterModel] | None = Field(default=None, max_length=2000)
    # Read only:
    file_name: str = ""
    duration_ms: int = 0
    can_write_chapters: bool = False  # MP3, M4A / M4B


class DetailsModel(ApiModel):
    title: str = Field(min_length=1, max_length=500)
    author: str = Field(max_length=500)
    narrator: str | None = Field(default=None, max_length=500)
    series: str | None = Field(default=None, max_length=500)
    series_number: str | None = Field(default=None, max_length=20)
    year: int | None = Field(default=None, ge=0, le=9999)
    genre: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    files: list[FileModel] | None = None  # in listening order


def _details_out(found: spoken_details.Details) -> DetailsModel:
    return DetailsModel(
        **{k: v for k, v in vars(found).items() if k != "files"},
        files=[
            FileModel(
                id=f.id,
                title=f.title,
                chapters=[
                    ChapterModel(start_ms=c.start_ms, title=c.title) for c in f.chapters or []
                ],
                file_name=f.file_name,
                duration_ms=f.duration_ms,
                can_write_chapters=f.can_write_chapters,
            )
            for f in found.files or []
        ],
    )


def _details_in(body: DetailsModel) -> spoken_details.Details:
    fields = body.model_dump(exclude={"files"})
    return spoken_details.Details(
        **fields,
        files=[
            spoken_details.FileDetails(
                id=f.id,
                title=f.title,
                chapters=[spoken_details.FileChapter(c.start_ms, c.title) for c in f.chapters]
                if f.chapters is not None
                else None,
            )
            for f in body.files
        ]
        if body.files is not None
        else None,
    )


@router.get("/shows/{album_id}/details")
async def get_details(album_id: uuid.UUID, caller: AdminCaller, session: DbSession) -> DetailsModel:
    """What "Edit details" starts from."""
    del caller
    found = await spoken_details.details(session, album_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown show or book")
    return _details_out(found)


class ChangedOut(ApiModel):
    id: uuid.UUID  # the show's / book's id afterwards (it changes with its title)


@router.put("/shows/{album_id}/details")
async def change_details(
    album_id: uuid.UUID,
    body: DetailsModel,
    request: Request,
    caller: AdminCaller,
    session: DbSession,
) -> ChangedOut:
    """Writes the details into the files (and moves the folder when the title / author
    changes), then rescans the book."""
    del caller
    scans: ScanManager = request.app.state.scans
    try:
        new_id = await spoken_details.change(session, scans, album_id, _details_in(body))
    except spoken_details.DetailsError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    return ChangedOut(id=new_id)


@router.delete("/shows/{album_id}/bookmarks", status_code=status.HTTP_204_NO_CONTENT)
async def forget_show(album_id: uuid.UUID, caller: CurrentCaller, session: DbSession) -> None:
    """Removes the user's bookmarks of a show / book: out of "Continue listening"
    (dismissed), or started over."""
    if await spoken.show(session, caller.user, album_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown show or book")
    await bookmarks.remove_for_album(session, caller.user, album_id)
    await session.commit()


# --- Audible (Edit details: "Look up on Audible") -------------------------------------


class AudibleBookOut(ApiModel):
    asin: str
    title: str
    authors: list[str]
    narrators: list[str]
    series: str | None
    series_number: str | None
    duration_ms: int | None
    cover_url: str | None
    url: str | None


class AudibleChapterOut(ApiModel):
    start_ms: int
    length_ms: int
    title: str


class AudibleChaptersOut(ApiModel):
    asin: str
    runtime_ms: int
    intro_ms: int  # Audible's jingle at the start of its file
    outro_ms: int
    accurate: bool
    chapters: list[AudibleChapterOut]


async def _audible_region(session: DbSession) -> str:
    services = await server_settings.get_external_services(session)
    if not services.audible:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Audible lookups are off (Settings → External services)"
        )
    return services.audible_region


@router.get("/audible/search")
async def audible_search(
    title: str, request: Request, caller: AdminCaller, session: DbSession, author: str | None = None
) -> list[AudibleBookOut]:
    del caller
    region = await _audible_region(session)
    try:
        found = await books.audible(request.app.state.http, title, author, region)
    except ExternalServiceError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return [
        AudibleBookOut(
            asin=c.id.removeprefix("audible:"),
            title=c.title,
            authors=c.authors,
            narrators=c.narrators,
            series=c.series,
            series_number=c.series_number,
            duration_ms=c.duration_ms,
            cover_url=c.cover_url,
            url=c.url,
        )
        for c in found
    ]


@router.get("/audible/{asin}/chapters")
async def audible_chapters(
    asin: str, request: Request, caller: AdminCaller, session: DbSession
) -> AudibleChaptersOut:
    del caller
    region = await _audible_region(session)
    try:
        found = await books.audible_chapters(request.app.state.http, asin, region)
    except ExternalServiceError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audible has no chapter list for this book")
    return AudibleChaptersOut(
        asin=found.asin,
        runtime_ms=found.runtime_ms,
        intro_ms=found.intro_ms,
        outro_ms=found.outro_ms,
        accurate=found.accurate,
        chapters=[
            AudibleChapterOut(start_ms=c.start_ms, length_ms=c.length_ms, title=c.title)
            for c in found.chapters
        ],
    )
