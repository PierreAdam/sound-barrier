"""Transcripts of podcast episodes and audiobook files (speech to text).

The speech recognition does not run on the server: a worker (the companion app in
`transcriber/`, on a PC with a GPU) signs in with a worker token, claims a file, downloads
it, transcribes it and sends the timed lines back. Nothing ever connects to the worker.

- A claim is a lease (LEASE), renewed by the worker's progress reports. A worker that
  stops (PC turned off) loses its file when the lease runs out: another worker can take
  it. Two workers (two GPUs) never get the same file.
- A transcript is kept in the database (with the timing of each word) and written as a
  `.lrc` file next to the audio (lines only, for other players), marked as ours (LRC_MARKER):
  a `.lrc` we did not write is never replaced, and removing a transcript removes only ours.
- Transcripts are served like synced lyrics (services/lyrics.py), so the web UI's "Now
  playing" and karaoke view and the Subsonic apps show them.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, delete, false, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import generate_api_key, hash_api_key
from app.models import Album, MusicFolder, Song, Transcript, WorkerToken
from app.services import browsing, music_folders

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=10)
TOKEN_PREFIX = "sbw_"
LRC_MARKER = "[re:Sound-Barrier transcriber]"
WORKING, DONE, FAILED = "working", "done", "failed"
_CANDIDATES = 20  # files tried per claim (another worker may take some meanwhile)


class NotClaimedError(Exception):
    """The file is not (or no longer) this worker's: another worker took it after the
    lease ran out, or an admin removed the transcript."""


# --- worker tokens ------------------------------------------------------------


async def create_token(
    session: AsyncSession, name: str, created_by: uuid.UUID | None
) -> tuple[WorkerToken, str]:
    """A new token and its secret, shown once (only its hash is kept)."""
    secret = TOKEN_PREFIX + generate_api_key()
    token = WorkerToken(name=name.strip(), token_hash=hash_api_key(secret), created_by=created_by)
    session.add(token)
    await session.flush()
    return token, secret


async def list_tokens(session: AsyncSession) -> Sequence[WorkerToken]:
    return (await session.scalars(select(WorkerToken).order_by(WorkerToken.created_at))).all()


async def revoke_token(session: AsyncSession, token_id: uuid.UUID) -> bool:
    """Its files being worked on go back to the queue."""
    token = await session.get(WorkerToken, token_id)
    if token is None:
        return False
    await session.execute(
        delete(Transcript).where(Transcript.worker_id == token_id, Transcript.status == WORKING)
    )
    await session.delete(token)
    return True


async def resolve_token(session: AsyncSession, secret: str) -> WorkerToken | None:
    if not secret.startswith(TOKEN_PREFIX):
        return None
    token = await session.scalar(
        select(WorkerToken).where(WorkerToken.token_hash == hash_api_key(secret))
    )
    if token is not None:
        token.last_used_at = datetime.now(UTC)
    return token


# --- what there is to do -------------------------------------------------------


async def _spoken_folders(session: AsyncSession) -> dict[int, MusicFolder]:
    """The podcasts and audiobooks folders that are on."""
    kinds = [k for k in await browsing.enabled_kinds(session) if k in music_folders.SPOKEN_KINDS]
    if not kinds:
        return {}
    folders = await session.scalars(select(MusicFolder).where(MusicFolder.kind.in_(kinds)))
    return {folder.id: folder for folder in folders}


def _claimable(now: datetime, retry_failed: bool) -> ColumnElement[bool]:
    """For an existing row: may it be (re)claimed?"""
    return or_(
        and_(Transcript.status == WORKING, Transcript.lease_until < now),
        and_(true() if retry_failed else false(), Transcript.status == FAILED),
    )


@dataclass
class BookStatus:
    album: Album
    kind: str
    files: int = 0
    duration_ms: int = 0
    done: int = 0
    working: int = 0
    failed: int = 0

    @property
    def pending(self) -> int:
        return self.files - self.done - self.working - self.failed


async def books(
    session: AsyncSession, kind: str | None = None, album_id: uuid.UUID | None = None
) -> list[BookStatus]:
    """Every show / book (or only one) with how far its transcription is, by title."""
    folders = await _spoken_folders(session)
    if kind is not None:
        folders = {i: f for i, f in folders.items() if f.kind == kind}
    if not folders:
        return []
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(
                Song.album_id,
                Song.music_folder_id,
                Song.duration_ms,
                Transcript.status,
                Transcript.lease_until,
            )
            .outerjoin(Transcript, Transcript.song_id == Song.id)
            .where(
                Song.missing_since.is_(None),
                Song.music_folder_id.in_(list(folders)),
                Song.album_id == album_id if album_id else true(),
            )
        )
    ).all()
    albums = {
        album.id: album
        for album in await session.scalars(
            select(Album).where(Album.id.in_({row.album_id for row in rows}))
        )
    }
    statuses: dict[uuid.UUID, BookStatus] = {}
    for row in rows:
        album = albums.get(row.album_id)
        if album is None:
            continue
        status = statuses.setdefault(album.id, BookStatus(album, folders[row.music_folder_id].kind))
        status.files += 1
        status.duration_ms += row.duration_ms
        if row.status == DONE:
            status.done += 1
        elif row.status == FAILED:
            status.failed += 1
        elif row.status == WORKING and row.lease_until is not None and row.lease_until >= now:
            status.working += 1  # an expired claim is waiting again
    return sorted(statuses.values(), key=lambda s: s.album.sort_name.casefold())


@dataclass
class FileStatus:
    song: Song
    status: str  # "pending", "working", "done", "failed"
    progress: float
    worker_name: str | None
    error: str | None
    updated_at: datetime | None


async def book_files(session: AsyncSession, album_id: uuid.UUID) -> list[FileStatus]:
    """The files of a show / book, in order, with their transcription."""
    folders = await _spoken_folders(session)
    if not folders:
        return []
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(Song, Transcript)
            .outerjoin(Transcript, Transcript.song_id == Song.id)
            .where(
                Song.album_id == album_id,
                Song.missing_since.is_(None),
                Song.music_folder_id.in_(list(folders)),
            )
            .order_by(Song.disc_number.nulls_first(), Song.track_number.nulls_first(), Song.path)
        )
    ).all()
    found: list[FileStatus] = []
    for row in rows:
        song: Song = row[0]
        transcript = cast("Transcript | None", row[1])  # none yet: outer join
        if transcript is None or (
            transcript.status == WORKING
            and transcript.lease_until is not None
            and transcript.lease_until < now
        ):
            found.append(FileStatus(song, "pending", 0.0, None, None, None))
        else:
            found.append(
                FileStatus(
                    song,
                    transcript.status,
                    transcript.progress,
                    transcript.worker_name,
                    transcript.error,
                    transcript.updated_at,
                )
            )
    return found


@dataclass
class Working:
    transcript: Transcript
    song: Song
    album: Album


async def working(session: AsyncSession) -> list[Working]:
    """The files being transcribed right now (a live lease)."""
    rows = (
        await session.execute(
            select(Transcript, Song, Album)
            .join(Song, Song.id == Transcript.song_id)
            .join(Album, Album.id == Song.album_id)
            .where(Transcript.status == WORKING, Transcript.lease_until >= datetime.now(UTC))
            .order_by(Transcript.created_at)
        )
    ).all()
    return [Working(t, s, a) for t, s, a in rows]


# --- the work ------------------------------------------------------------------


async def audio_path(session: AsyncSession, song_id: uuid.UUID) -> Path | None:
    """The file of a podcast episode / audiobook file (never music: workers only get those)."""
    song = await session.get(Song, song_id)
    folder = (await _spoken_folders(session)).get(song.music_folder_id) if song else None
    if song is None or folder is None or song.missing_since is not None:
        return None
    return Path(folder.path) / song.path


@dataclass
class Claimed:
    song: Song
    album: Album
    kind: str
    path: Path
    lease_until: datetime


async def claim(
    session: AsyncSession,
    worker: WorkerToken,
    *,
    album_id: uuid.UUID | None = None,
    song_id: uuid.UUID | None = None,
    kind: str | None = None,
    retry_failed: bool = False,
    instance: str | None = None,
) -> Claimed | None:
    """The next file without a transcript (of a book, or a given one), now this worker's
    for LEASE; None if there is nothing (left) to do."""
    folders = await _spoken_folders(session)
    if kind is not None:
        folders = {i: f for i, f in folders.items() if f.kind == kind}
    if not folders:
        return None
    now = datetime.now(UTC)
    candidates = (
        await session.execute(
            select(Song, Album)
            .join(Album, Album.id == Song.album_id)
            .outerjoin(Transcript, Transcript.song_id == Song.id)
            .where(
                Song.missing_since.is_(None),
                Song.music_folder_id.in_(list(folders)),
                Song.album_id == album_id if album_id else true(),
                Song.id == song_id if song_id else true(),
                or_(Transcript.song_id.is_(None), _claimable(now, retry_failed)),
            )
            .order_by(
                func.lower(Album.sort_name),
                Album.id,
                Song.disc_number.nulls_first(),
                Song.track_number.nulls_first(),
                Song.path,
            )
            .limit(_CANDIDATES)
        )
    ).all()
    name = f"{worker.name} · {instance}" if instance else worker.name
    until = now + LEASE
    for song, album in candidates:
        claimed = {
            "status": WORKING,
            "worker_id": worker.id,
            "worker_name": name,
            "lease_until": until,
            "progress": 0.0,
            "error": None,
        }
        taken = await session.scalar(
            insert(Transcript)
            .values(song_id=song.id, **claimed)
            .on_conflict_do_update(
                index_elements=[Transcript.song_id],
                set_={**claimed, "updated_at": func.now()},
                where=_claimable(now, retry_failed),
            )
            .returning(Transcript.song_id)
        )
        if taken is not None:
            folder = folders[song.music_folder_id]
            return Claimed(song, album, folder.kind, Path(folder.path) / song.path, until)
    return None


async def _own(session: AsyncSession, worker: WorkerToken, song_id: uuid.UUID) -> Transcript:
    transcript = await session.get(Transcript, song_id, with_for_update=True)
    if transcript is None or transcript.status != WORKING or transcript.worker_id != worker.id:
        raise NotClaimedError(song_id)
    return transcript


async def renew(
    session: AsyncSession, worker: WorkerToken, song_id: uuid.UUID, progress: float | None
) -> datetime:
    """The worker is still at it: the lease starts again (and the progress is shown)."""
    transcript = await _own(session, worker, song_id)
    until = datetime.now(UTC) + LEASE
    transcript.lease_until = until
    if progress is not None:
        transcript.progress = min(max(progress, 0.0), 1.0)
    return until


async def release(session: AsyncSession, worker: WorkerToken, song_id: uuid.UUID) -> None:
    """The worker gives the file back (e.g. stopped with Ctrl+C): waiting again."""
    try:
        transcript = await _own(session, worker, song_id)
    except NotClaimedError:
        return
    await session.delete(transcript)


async def fail(session: AsyncSession, worker: WorkerToken, song_id: uuid.UUID, error: str) -> None:
    """Not taken again unless asked (retry_failed, or "Retry" in Settings)."""
    transcript = await _own(session, worker, song_id)
    transcript.status = FAILED
    transcript.error = error[:2000]
    transcript.lease_until = None


def _spaced_words(given: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Words with a trailing space when a new word follows, but the last one (the format
    of services/lyrics.py). A space around either word separates them (Whisper puts it
    before a word); none glues them (French "C'" + "était")."""
    words: list[dict[str, Any]] = []
    for index, word in enumerate(given):
        raw = str(word["text"])
        text = " ".join(raw.split())
        if not text:
            continue
        following = str(given[index + 1]["text"]) if index + 1 < len(given) else ""
        space = raw[-1:].isspace() or following[:1].isspace()
        words.append({"startMs": int(word["startMs"]), "text": text + (" " if space else "")})
    if words:
        words[-1]["text"] = words[-1]["text"].rstrip()
    return words


def _clean_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sorted, without empty lines."""
    cleaned: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda line: line["startMs"]):
        text = " ".join(str(line["text"]).split())
        if not text:
            continue
        words = _spaced_words(line.get("words") or [])
        start = int(line["startMs"])
        cleaned.append(
            {
                "startMs": start,
                "endMs": max(int(line.get("endMs") or start), start),
                "text": text,
                "words": words or None,
            }
        )
    return cleaned


def _stamp(ms: int) -> str:
    """LRC time: minutes may pass 99 (a long audiobook file)."""
    minutes, rest = divmod(max(ms, 0), 60_000)
    return f"[{minutes:02d}:{rest // 1000:02d}.{rest % 1000 // 10:02d}]"


def to_lrc(title: str, artist: str, model: str | None, lines: list[dict[str, Any]]) -> str:
    header = [LRC_MARKER, f"[ti:{title}]", f"[ar:{artist}]"]
    if model:
        header.append(f"[by:{model}]")
    return "\n".join([*header, *(f"{_stamp(line['startMs'])}{line['text']}" for line in lines)])


def is_ours(lrc: Path) -> bool:
    try:
        with lrc.open(encoding="utf-8", errors="replace") as file:
            return LRC_MARKER in file.read(4096)
    except OSError:
        return False


def _write_lrc(audio: Path, content: str) -> bool:
    """Next to the audio, unless a `.lrc` of someone else is there. False: not written."""
    lrc = audio.with_suffix(".lrc")
    if lrc.exists() and not is_ours(lrc):
        logger.info("%s exists and is not ours: kept, the transcript stays in the database", lrc)
        return False
    temporary = lrc.with_name(f".{lrc.name}.tmp")
    try:
        temporary.write_text(content + "\n", encoding="utf-8", newline="\n")
        temporary.replace(lrc)
    except OSError as error:
        logger.warning("Cannot write %s: %s", lrc, error)
        temporary.unlink(missing_ok=True)
        return False
    return True


def _remove_lrc(audio: Path) -> None:
    lrc = audio.with_suffix(".lrc")
    if is_ours(lrc):
        try:
            lrc.unlink()
        except OSError as error:
            logger.warning("Cannot remove %s: %s", lrc, error)


async def save(
    session: AsyncSession,
    worker: WorkerToken,
    song_id: uuid.UUID,
    *,
    model: str | None,
    language: str | None,
    lines: list[dict[str, Any]],
    part: int = 0,
    last: bool = True,
) -> Transcript:
    """The worker's result: kept, and written as a `.lrc` next to the audio.

    A long file comes in parts (reverse proxies limit the size of a request): part 0
    starts over, the next ones add their lines, the last one finishes the transcript.
    """
    transcript = await _own(session, worker, song_id)
    song = await session.get(Song, song_id)
    folder = await session.get(MusicFolder, song.music_folder_id) if song else None
    if song is None or folder is None:
        raise NotClaimedError(song_id)
    received = lines if part == 0 else [*(transcript.lines or []), *lines]
    if not last:
        transcript.lines = received
        transcript.lease_until = datetime.now(UTC) + LEASE
        return transcript
    cleaned = _clean_lines(received)
    transcript.status = DONE
    transcript.lines = cleaned
    transcript.model = model
    transcript.language = language
    transcript.progress = 1.0
    transcript.lease_until = None
    transcript.error = None
    transcript.lrc_written = bool(cleaned) and await asyncio.to_thread(
        _write_lrc,
        Path(folder.path) / song.path,
        to_lrc(song.title, song.display_artist, model, cleaned),
    )
    return transcript


# --- admins ----------------------------------------------------------------------


async def _book_rows(
    session: AsyncSession, album_id: uuid.UUID, *where: ColumnElement[bool]
) -> list[tuple[Transcript, Path]]:
    rows = (
        await session.execute(
            select(Transcript, Song.path, MusicFolder.path)
            .join(Song, Song.id == Transcript.song_id)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .where(Song.album_id == album_id, *where)
        )
    ).all()
    return [(t, Path(folder) / path) for t, path, folder in rows]


async def remove_book(session: AsyncSession, album_id: uuid.UUID) -> int:
    """Forgets the transcripts of a show / book (and removes our `.lrc` files): it can be
    transcribed again. Returns how many files had one."""
    rows = await _book_rows(session, album_id)
    for transcript, audio in rows:
        if transcript.lrc_written:
            await asyncio.to_thread(_remove_lrc, audio)
        await session.delete(transcript)
    return len(rows)


async def retry_book(session: AsyncSession, album_id: uuid.UUID) -> int:
    """The failed files of a show / book wait again."""
    rows = await _book_rows(session, album_id, Transcript.status == FAILED)
    for transcript, _ in rows:
        await session.delete(transcript)
    return len(rows)


async def done(session: AsyncSession, song_id: uuid.UUID) -> Transcript | None:
    """The finished transcript of a file, if any (services/lyrics.py)."""
    transcript = await session.get(Transcript, song_id)
    return transcript if transcript is not None and transcript.status == DONE else None
