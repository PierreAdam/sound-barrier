"""Transcripts (services/transcripts.py).

- `/api/transcriber/...`: the transcription workers (the companion app, `transcriber/`),
  signed in with a worker token (`Authorization: Bearer sbw_...`). They can list what
  waits, claim a file, download it and send its transcript, nothing else.
- `/api/transcripts/...`: admins (web UI, Settings): worker tokens, progress, and the
  transcripts of a show / book (remove, retry).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field
from starlette.responses import FileResponse

from app import __version__
from app.api.deps import AdminCaller, ApiModel, DbSession
from app.core.throttle import LoginThrottle, client_address, minutes
from app.models import WorkerToken
from app.services import transcripts

# The worker checks it: a server with an older API tells it to update Sound-Barrier.
WORKER_API_VERSION = 1

worker_router = APIRouter(prefix="/transcriber", tags=["transcription workers"])
admin_router = APIRouter(prefix="/transcripts", tags=["transcripts"])


async def current_worker(request: Request, session: DbSession) -> WorkerToken:
    """The worker token of the request; failures count like failed sign-ins (per IP)."""
    throttle: LoginThrottle = request.app.state.throttle
    address = client_address(request)
    blocked = throttle.blocked_for(address)
    if blocked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts: try again in {minutes(blocked)} minutes",
        )
    scheme, _, secret = request.headers.get("authorization", "").partition(" ")
    worker = (
        await transcripts.resolve_token(session, secret.strip())
        if scheme.lower() == "bearer"
        else None
    )
    if worker is None:
        throttle.failure(address)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Unknown or revoked worker token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    throttle.success(address)
    await session.commit()  # last_used_at
    return worker


CurrentWorker = Annotated[WorkerToken, Depends(current_worker)]


def _not_claimed() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "This file is no longer yours (the claim ran out and another worker took it, "
        "or its transcript was removed)",
    )


# --- models ------------------------------------------------------------------------


class BookOut(ApiModel):
    id: uuid.UUID
    kind: str  # podcasts, audiobooks
    title: str
    author: str
    cover_art: str | None
    files: int
    duration_ms: int
    done: int
    working: int
    failed: int
    pending: int


def _book(book: transcripts.BookStatus) -> BookOut:
    album = book.album
    return BookOut(
        id=album.id,
        kind=book.kind,
        title=album.name,
        author=album.display_artist,
        cover_art=str(album.artwork_id) if album.artwork_id else None,
        files=book.files,
        duration_ms=book.duration_ms,
        done=book.done,
        working=book.working,
        failed=book.failed,
        pending=book.pending,
    )


class FileOut(ApiModel):
    id: uuid.UUID
    title: str
    file_name: str
    duration_ms: int
    size: int
    status: str  # pending, working, done, failed
    progress: float
    worker: str | None
    error: str | None
    updated_at: datetime | None


def _file(found: transcripts.FileStatus) -> FileOut:
    return FileOut(
        id=found.song.id,
        title=found.song.title,
        file_name=found.song.path.rsplit("/", 1)[-1],
        duration_ms=found.song.duration_ms,
        size=found.song.size,
        status=found.status,
        progress=found.progress,
        worker=found.worker_name,
        error=found.error,
        updated_at=found.updated_at,
    )


class BookFilesOut(ApiModel):
    book: BookOut
    files: list[FileOut]


async def _book_files(session: DbSession, album_id: uuid.UUID) -> BookFilesOut:
    found = await transcripts.books(session, album_id=album_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such podcast or audiobook")
    files = await transcripts.book_files(session, album_id)
    return BookFilesOut(book=_book(found[0]), files=[_file(f) for f in files])


# --- workers ---------------------------------------------------------------------


class HelloOut(ApiModel):
    server: str
    version: str
    api_version: int
    worker: str


@worker_router.get("/hello")
async def hello(worker: CurrentWorker) -> HelloOut:
    """Checks the token (and the server's version)."""
    return HelloOut(
        server="Sound-Barrier",
        version=__version__,
        api_version=WORKER_API_VERSION,
        worker=worker.name,
    )


@worker_router.get("/books")
async def worker_books(
    worker: CurrentWorker, session: DbSession, kind: str | None = None
) -> list[BookOut]:
    del worker
    return [_book(b) for b in await transcripts.books(session, kind)]


@worker_router.get("/books/{album_id}")
async def worker_book(
    album_id: uuid.UUID, worker: CurrentWorker, session: DbSession
) -> BookFilesOut:
    del worker
    return await _book_files(session, album_id)


class ClaimIn(ApiModel):
    album_id: uuid.UUID | None = None
    song_id: uuid.UUID | None = None
    kind: str | None = None
    retry_failed: bool = False
    instance: str | None = Field(default=None, max_length=60)  # e.g. "GPU 0"


class ClaimOut(ApiModel):
    song_id: uuid.UUID
    album_id: uuid.UUID
    kind: str
    book: str
    author: str
    title: str
    file_name: str
    suffix: str
    size: int
    duration_ms: int
    lease_until: datetime
    lease_seconds: int


@worker_router.post("/claim", response_model=None)
async def claim(body: ClaimIn, worker: CurrentWorker, session: DbSession) -> ClaimOut | Response:
    """The next file to transcribe, now this worker's; 204: nothing to do."""
    claimed = await transcripts.claim(
        session,
        worker,
        album_id=body.album_id,
        song_id=body.song_id,
        kind=body.kind,
        retry_failed=body.retry_failed,
        instance=body.instance,
    )
    await session.commit()
    if claimed is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    song = claimed.song
    return ClaimOut(
        song_id=song.id,
        album_id=claimed.album.id,
        kind=claimed.kind,
        book=claimed.album.name,
        author=claimed.album.display_artist,
        title=song.title,
        file_name=claimed.path.name,
        suffix=song.suffix,
        size=song.size,
        duration_ms=song.duration_ms,
        lease_until=claimed.lease_until,
        lease_seconds=int(transcripts.LEASE.total_seconds()),
    )


@worker_router.get("/files/{song_id}/audio")
async def audio(song_id: uuid.UUID, worker: CurrentWorker, session: DbSession) -> FileResponse:
    """The original file (the server does not transcode: its timing is the players')."""
    del worker
    path = await transcripts.audio_path(session, song_id)
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such podcast or audiobook file")
    return FileResponse(path, filename=path.name)


class ProgressIn(ApiModel):
    progress: float | None = Field(default=None, ge=0, le=1)


class LeaseOut(ApiModel):
    lease_until: datetime


@worker_router.post("/files/{song_id}/progress")
async def progress(
    song_id: uuid.UUID, body: ProgressIn, worker: CurrentWorker, session: DbSession
) -> LeaseOut:
    """Renews the claim (send one at least every few minutes)."""
    try:
        until = await transcripts.renew(session, worker, song_id, body.progress)
    except transcripts.NotClaimedError:
        raise _not_claimed() from None
    await session.commit()
    return LeaseOut(lease_until=until)


@worker_router.post("/files/{song_id}/release", status_code=status.HTTP_204_NO_CONTENT)
async def release(song_id: uuid.UUID, worker: CurrentWorker, session: DbSession) -> None:
    """Gives the file back (stopped before the end)."""
    await transcripts.release(session, worker, song_id)
    await session.commit()


class FailIn(ApiModel):
    error: str = Field(max_length=10_000)


@worker_router.post("/files/{song_id}/fail", status_code=status.HTTP_204_NO_CONTENT)
async def fail(song_id: uuid.UUID, body: FailIn, worker: CurrentWorker, session: DbSession) -> None:
    try:
        await transcripts.fail(session, worker, song_id, body.error)
    except transcripts.NotClaimedError:
        raise _not_claimed() from None
    await session.commit()


class WordIn(ApiModel):
    start_ms: int = Field(ge=0)
    text: str


class LineIn(ApiModel):
    start_ms: int = Field(ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str
    words: list[WordIn] | None = None


class TranscriptIn(ApiModel):
    model: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=16)
    lines: list[LineIn]
    # A long transcript comes in parts: 0 starts over, `last` finishes it.
    part: int = Field(default=0, ge=0)
    last: bool = True


class SavedOut(ApiModel):
    lines: int  # received so far
    done: bool
    lrc_written: bool


@worker_router.put("/files/{song_id}/transcript")
async def save(
    song_id: uuid.UUID, body: TranscriptIn, worker: CurrentWorker, session: DbSession
) -> SavedOut:
    try:
        saved = await transcripts.save(
            session,
            worker,
            song_id,
            model=body.model,
            language=body.language,
            lines=[line.model_dump(by_alias=True) for line in body.lines],
            part=body.part,
            last=body.last,
        )
    except transcripts.NotClaimedError:
        raise _not_claimed() from None
    await session.commit()
    return SavedOut(
        lines=len(saved.lines or []),
        done=saved.status == transcripts.DONE,
        lrc_written=saved.lrc_written,
    )


# --- admins ----------------------------------------------------------------------


class TokenOut(ApiModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


def _token(token: WorkerToken) -> TokenOut:
    return TokenOut(
        id=token.id, name=token.name, created_at=token.created_at, last_used_at=token.last_used_at
    )


class NewTokenIn(ApiModel):
    name: str = Field(min_length=1, max_length=60)


class NewTokenOut(ApiModel):
    token: TokenOut
    secret: str  # shown once


@admin_router.get("/tokens")
async def tokens(caller: AdminCaller, session: DbSession) -> list[TokenOut]:
    del caller
    return [_token(t) for t in await transcripts.list_tokens(session)]


@admin_router.post("/tokens")
async def create_token(body: NewTokenIn, caller: AdminCaller, session: DbSession) -> NewTokenOut:
    if not body.name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A name is needed")
    token, secret = await transcripts.create_token(session, body.name, caller.user.id)
    await session.commit()
    await session.refresh(token)
    return NewTokenOut(token=_token(token), secret=secret)


@admin_router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, caller: AdminCaller, session: DbSession) -> None:
    del caller
    if not await transcripts.revoke_token(session, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such token")
    await session.commit()


class WorkingOut(ApiModel):
    song_id: uuid.UUID
    album_id: uuid.UUID
    book: str
    title: str
    worker: str | None
    progress: float
    started_at: datetime
    updated_at: datetime


class OverviewOut(ApiModel):
    books: list[BookOut]
    working: list[WorkingOut]


@admin_router.get("")
async def overview(caller: AdminCaller, session: DbSession) -> OverviewOut:
    del caller
    return OverviewOut(
        books=[_book(b) for b in await transcripts.books(session)],
        working=[
            WorkingOut(
                song_id=w.song.id,
                album_id=w.album.id,
                book=w.album.name,
                title=w.song.title,
                worker=w.transcript.worker_name,
                progress=w.transcript.progress,
                started_at=w.transcript.created_at,
                updated_at=w.transcript.updated_at,
            )
            for w in await transcripts.working(session)
        ],
    )


@admin_router.get("/books/{album_id}")
async def admin_book(album_id: uuid.UUID, caller: AdminCaller, session: DbSession) -> BookFilesOut:
    del caller
    return await _book_files(session, album_id)


class CountOut(ApiModel):
    count: int


@admin_router.delete("/books/{album_id}")
async def remove_book(album_id: uuid.UUID, caller: AdminCaller, session: DbSession) -> CountOut:
    """Removes the transcripts of a show / book (and our `.lrc` files)."""
    del caller
    count = await transcripts.remove_book(session, album_id)
    await session.commit()
    return CountOut(count=count)


@admin_router.post("/books/{album_id}/retry")
async def retry_book(album_id: uuid.UUID, caller: AdminCaller, session: DbSession) -> CountOut:
    """Its failed files wait again."""
    del caller
    count = await transcripts.retry_book(session, album_id)
    await session.commit()
    return CountOut(count=count)
