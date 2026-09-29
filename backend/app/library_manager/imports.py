"""Import workflow: jobs -> one task per album folder -> identify -> (auto) apply or review.

A single background worker runs the work items one at a time, and every Tagger call goes
through one dedicated thread (beets is synchronous and not thread-safe). State lives in
the import_job / import_task tables, so the page can poll it and a restart loses nothing
but the work in progress (marked as interrupted).
"""

import asyncio
import contextlib
import itertools
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, update

from app.core.db import Database
from app.external import ExternalServiceError, books
from app.library_manager import duplicates, files, spoken_review, transcode
from app.library_manager.tagger import (
    Candidate,
    Identification,
    ImportMode,
    ImportOptions,
    ItemInfo,
    Recommendation,
    Tagger,
    TaggerError,
)
from app.models import ImportJob, ImportTask
from app.services import music_folders, server_settings
from app.services.scans import ScanManager

logger = logging.getLogger(__name__)

# Task statuses
QUEUED, ANALYZING, PENDING, APPLYING = "queued", "analyzing", "pending", "applying"
CONVERTING = "converting"  # lossless -> MP3, before applying
IMPORTED, SKIPPED, FAILED = "imported", "skipped", "failed"
ACTIVE_STATUSES = (QUEUED, ANALYZING, CONVERTING, APPLYING)


# Job kinds
IMPORT, ADOPT = "import", "adopt"
# Podcasts / audiobooks: reviewed, then placed into their library folder (spoken_review.py).
PODCAST, AUDIOBOOK = spoken_review.PODCAST, spoken_review.AUDIOBOOK
SPOKEN_FOLDERS = {PODCAST: music_folders.PODCASTS, AUDIOBOOK: music_folders.AUDIOBOOKS}
MAX_COVER_BYTES = 10 * 1024 * 1024

# Work someone is waiting for in the web UI: run before the queued matching.
_URGENT = frozenset({"apply", "apply_spoken", "search"})


class ImportRequestError(Exception):
    """A request that cannot be done (shown to the admin)."""


def _now() -> datetime:
    return datetime.now(UTC)


class ImportManager:
    def __init__(
        self,
        db: Database,
        scans: ScanManager,
        tagger: Tagger,
        staging_root: Path,
        http: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._db = db
        # External lookups of audiobooks / podcasts (a getter: tests swap the client).
        self._http = http
        self._scans = scans
        self.tagger = tagger
        self._staging_root = staging_root  # temporary files (e.g. converted MP3s)
        # (priority, order, kind, id): decisions taken in the web UI (apply, as-is, search)
        # go before the matching of queued albums, which can be hundreds (e.g. "Add all
        # to beets"); same priority: first come, first served.
        self._queue: asyncio.PriorityQueue[tuple[int, int, str, int]] = asyncio.PriorityQueue()
        self._order = itertools.count()
        self._working = False
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="tagger")
        self._worker: asyncio.Task[None] | None = None

    # --- lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        await self._recover_interrupted_work()
        self._worker = asyncio.create_task(self._work(), name="import-worker")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def _recover_interrupted_work(self) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(ImportJob)
                .where(ImportJob.status.in_(("queued", "running")))
                .values(
                    status="failed", error="Interrupted by a server restart", finished_at=_now()
                )
            )
            await session.execute(
                update(ImportTask)
                .where(ImportTask.status.in_(ACTIVE_STATUSES))
                .values(status=FAILED, error="Interrupted by a server restart: retry it")
            )
            await session.commit()

    @property
    def busy(self) -> bool:
        """Something is being imported or waits to be (e.g. a conversion may be running)."""
        return self._working or not self._queue.empty()

    def _enqueue(self, kind: str, item_id: int, *, urgent: bool | None = None) -> None:
        """`urgent`: someone waits for it in the web UI (default: decisions and searches)."""
        urgent = kind in _URGENT if urgent is None else urgent
        self._queue.put_nowait((0 if urgent else 1, next(self._order), kind, item_id))

    async def wait_idle(self) -> None:
        """Waits until all queued work is done (tests)."""
        await self._queue.join()

    # --- requests (called by the API) --------------------------------------------------

    async def create_job(self, user_id: uuid.UUID, sources: list[Path], kind: str = IMPORT) -> int:
        """kind: IMPORT (new music), ADOPT (album folders already in the library), PODCAST
        or AUDIOBOOK (reviewed, then placed into that library folder)."""
        async with self._db.session() as session:
            job = ImportJob(
                created_by=user_id, sources=[str(s) for s in sources], status="queued", kind=kind
            )
            session.add(job)
            await session.commit()
            job_id = job.id
        self._enqueue("job", job_id)
        return job_id

    async def decide(
        self, task_id: int, action: str, candidate_id: str | None = None, *, urgent: bool = True
    ) -> None:
        """action: apply (candidate_id), as_is, skip, retry. `urgent` (a decision taken in
        the web UI): done before the albums waiting to be matched."""
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id, with_for_update=True)
            if task is None:
                raise ImportRequestError("Unknown import task")
            if task.status in ACTIVE_STATUSES:
                raise ImportRequestError("This album is being processed, wait a moment")
            if action == "retry":
                if task.status not in (FAILED, SKIPPED, PENDING):
                    raise ImportRequestError(
                        "Only failed, skipped or pending albums can be retried"
                    )
                task.status, task.error, task.decision = QUEUED, None, None
                work = ("identify_spoken" if task.spoken is not None else "identify", task_id)
            elif action == "skip" and task.status == FAILED:
                # Dismissing an album that failed (e.g. interrupted by a restart).
                task.status, task.decision = SKIPPED, {"action": "skip"}
                work = None
            elif task.status != PENDING:
                raise ImportRequestError(f"This album is {task.status}, not waiting for a decision")
            elif action == "skip":
                task.status, task.decision, task.error = SKIPPED, {"action": "skip"}, None
                work = None
            elif task.spoken is not None:
                raise ImportRequestError("Audiobooks and podcasts are imported from their review")
            elif action == "as_is":
                task.status, task.decision, task.error = QUEUED, {"action": "as_is"}, None
                work = ("apply", task_id)
            elif action == "apply":
                if not any(c["id"] == candidate_id for c in task.candidates):
                    raise ImportRequestError("Unknown candidate")
                task.status, task.error = QUEUED, None
                task.decision = {"action": "apply", "candidateId": candidate_id}
                work = ("apply", task_id)
            else:
                raise ImportRequestError(f"Unknown action: {action}")
            await session.commit()
        if work is not None:
            self._enqueue(*work, urgent=urgent)

    async def decide_all(self, action: str, status: str) -> int:
        """`action` (skip or retry) for every album in `status` (pending or failed).
        Returns how many albums changed."""
        if action not in ("skip", "retry") or status not in (PENDING, FAILED):
            raise ImportRequestError("Only skip / retry of pending or failed albums")
        async with self._db.session() as session:
            ids = (
                await session.scalars(
                    select(ImportTask.id).where(ImportTask.status == status).order_by(ImportTask.id)
                )
            ).all()
        changed = 0
        for task_id in ids:
            try:
                await self.decide(task_id, action, urgent=False)  # a bulk: no hurry
            except ImportRequestError:
                continue  # changed meanwhile (e.g. being processed)
            changed += 1
        return changed

    async def review_counts(self) -> dict[str, int]:
        """Albums waiting for a decision and albums that failed, in all jobs."""
        async with self._db.session() as session:
            rows = await session.execute(
                select(ImportTask.status, func.count())
                .where(ImportTask.status.in_((PENDING, FAILED)))
                .group_by(ImportTask.status)
            )
            counts = {status: count for status, count in rows}
        return {"pending": counts.get(PENDING, 0), "failed": counts.get(FAILED, 0)}

    async def search(
        self,
        task_id: int,
        *,
        artist: str | None = None,
        album: str | None = None,
        release_id: str | None = None,
    ) -> None:
        if not self.tagger.supports_matching:
            raise ImportRequestError(
                "Searching needs MusicBrainz matching (beets), not available yet"
            )
        if not (release_id or artist or album):
            raise ImportRequestError("Give an artist and / or album, or a release id")
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id, with_for_update=True)
            if task is None or task.status != PENDING:
                raise ImportRequestError("Only albums waiting for a decision can be searched")
            task.status, task.error = QUEUED, None
            task.decision = {
                "action": "search",
                "artist": artist,
                "album": album,
                "releaseId": release_id,
            }
            await session.commit()
        self._enqueue("search", task_id)

    # --- audiobooks and podcasts (spoken_review.py) --------------------------------------

    async def import_spoken(self, task_id: int, metadata: spoken_review.SpokenMetadata) -> None:
        """The reviewed book / show goes into the library with this metadata."""
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id, with_for_update=True)
            if task is None or task.spoken is None:
                raise ImportRequestError("Unknown audiobook / podcast import")
            if task.status != PENDING:
                raise ImportRequestError(f"This one is {task.status}, not waiting for a review")
            known = {i["path"] for i in task.items}
            if not metadata.entries or any(e.path not in known for e in metadata.entries):
                raise ImportRequestError("The chapters do not match this import's files")
            if metadata.cover and not self._allowed_cover(task, metadata.cover):
                raise ImportRequestError("Unknown cover")
            task.status, task.error = QUEUED, None
            task.decision = {"action": "import", "metadata": metadata.to_json()}
            await session.commit()
        self._enqueue("apply_spoken", task_id, urgent=True)

    @staticmethod
    def _allowed_cover(task: ImportTask, cover: str) -> bool:
        """A cover of the task's folders / files, or an image URL."""
        source, _, value = cover.partition(":")
        spoken = task.spoken or {}
        if source == "folder":
            return value in spoken.get("images", [])
        if source == "embedded":
            return any(i["path"] == value and i.get("has_picture") for i in task.items)
        return source == "url" and value.startswith(("https://", "http://"))

    async def cover(self, task_id: int, cover: str) -> tuple[bytes, str] | None:
        """A folder / embedded cover of a waiting import (the review's preview)."""
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
        if task is None or task.spoken is None or not self._allowed_cover(task, cover):
            return None
        if cover.startswith("url:"):
            return None
        return await asyncio.to_thread(spoken_review.picture, cover)

    async def merge(self, task_id: int, into_id: int) -> None:
        """Appends a waiting book's files to another waiting book of the same import."""
        if task_id == into_id:
            raise ImportRequestError("Choose another book")
        async with self._db.session() as session:
            tasks = {
                t.id: t
                for t in (
                    await session.scalars(
                        select(ImportTask)
                        .where(ImportTask.id.in_((task_id, into_id)))
                        .with_for_update()
                    )
                ).all()
            }
            task, into = tasks.get(task_id), tasks.get(into_id)
            if task is None or into is None or task.spoken is None or into.spoken is None:
                raise ImportRequestError("Unknown audiobook / podcast import")
            if (
                task.job_id != into.job_id
                or PENDING not in (task.status, into.status)
                or (task.status != into.status)
            ):
                raise ImportRequestError("Only waiting books of the same import can be merged")
            kind = into.spoken["kind"]
            items = [spoken_review.SpokenFile.from_json(i) for i in into.items + task.items]
            proposal = spoken_review.SpokenMetadata.from_json(into.spoken["proposal"])
            added = spoken_review.order(
                kind, [spoken_review.SpokenFile.from_json(i) for i in task.items]
            )
            fresh = spoken_review.propose(kind, [Path(task.source_dir)], added)
            proposal.entries += fresh.entries
            if kind == PODCAST:
                proposal.entries.sort(key=lambda e: e.date or "", reverse=True)
            into.items = [i.to_json() for i in items]
            into.spoken = {
                **into.spoken,
                "folders": into.spoken["folders"] + task.spoken["folders"],
                "images": into.spoken["images"] + task.spoken["images"],
                "proposal": proposal.to_json(),
            }
            task.status, task.decision, task.error = (
                SKIPPED,
                {"action": "merged", "into": into_id},
                None,
            )
            await session.commit()

    async def lookup(self, task_id: int, title: str, author: str | None) -> None:
        """Searches the online catalogs again, with another title / author."""
        if not title.strip():
            raise ImportRequestError("Give a title to look for")
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
            if task is None or task.spoken is None or task.status != PENDING:
                raise ImportRequestError("Only waiting audiobooks / podcasts can be looked up")
            kind = task.spoken["kind"]
            duration = sum(i["duration_ms"] for i in task.items)
            files = len(task.items)
        candidates, lookup = await self._look_up(kind, title.strip(), author, duration, files)
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id, with_for_update=True)
            if task is None or task.spoken is None:
                return
            task.candidates = candidates
            task.spoken = {**task.spoken, "lookup": lookup}
            await session.commit()

    async def _look_up(
        self, kind: str, title: str, author: str | None, duration_ms: int, files: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Candidates from the enabled catalogs (best first, catalog by catalog), and the
        query / errors. `files`: MusicBrainz editions with that many tracks come first."""
        async with self._db.session() as session:
            services = await server_settings.get_external_services(session)
        http = self._http() if self._http else None
        found: list[books.BookCandidate] = []
        errors: list[str] = []
        searches: list[tuple[str, Any]] = []
        if http is not None and kind == AUDIOBOOK:
            if services.audible:
                searches.append(
                    ("Audible", books.audible(http, title, author, services.audible_region))
                )
            if services.musicbrainz:
                searches.append(
                    ("MusicBrainz", books.musicbrainz_audiobooks(http, title, author, files))
                )
            if services.open_library:
                searches.append(("Open Library", books.open_library(http, title, author)))
        elif http is not None and services.itunes:
            searches.append(("iTunes", books.itunes_podcasts(http, title)))
        results = await asyncio.gather(*(s for _, s in searches), return_exceptions=True)
        for (name, _), result in zip(searches, results, strict=True):
            if isinstance(result, ExternalServiceError):
                errors.append(str(result))
            elif isinstance(result, BaseException):
                logger.warning("%s lookup failed", name, exc_info=result)
                errors.append(f"{name}: {result}")
            else:
                for candidate in result:  # MusicBrainz track titles, cleaned like file names
                    for track in candidate.tracks:
                        track["title"] = spoken_review.clean_chapter(track["title"])
                found += _ranked(result, duration_ms)
        query = {"title": title, "author": author}
        return [c.to_json() for c in found], {"query": query, "errors": errors}

    async def _run_spoken_job(self, job_id: int, sources: list[Path], kind: str) -> None:
        """Podcasts / audiobooks: one task per book / show, each analyzed then waiting
        for its review."""
        status, error = "done", None
        try:
            units: list[list[Path]] = []
            for source in sources:
                units += await self._in_thread(spoken_review.find_units, source)
            async with self._db.session() as session:
                tasks = [
                    ImportTask(
                        job_id=job_id,
                        source_dir=str(unit[0]),
                        status=QUEUED,
                        spoken={"kind": kind, "folders": [str(f) for f in unit]},
                    )
                    for unit in units
                ]
                session.add_all(tasks)
                await session.commit()
                task_ids = [t.id for t in tasks]
            for task_id in task_ids:
                await self._identify_spoken(task_id)
            if not units:
                error = "No audio files found"
        except Exception as exc:
            logger.exception("Import job %s failed", job_id)
            status, error = "failed", str(exc)
        async with self._db.session() as session:
            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(status=status, error=error, finished_at=_now())
            )
            await session.commit()

    async def _identify_spoken(self, task_id: int) -> None:
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
            if task is None or task.spoken is None:
                return
            task.status = ANALYZING
            await session.commit()
            kind = task.spoken["kind"]
            folders = [Path(f) for f in task.spoken["folders"]]

        def analyze() -> tuple[
            list[spoken_review.SpokenFile], spoken_review.SpokenMetadata, list[str]
        ]:
            items = spoken_review.read_files(folders)
            if not items:
                raise TaggerError("No readable audio files in this folder")
            images = [str(p) for p in spoken_review.folder_images(folders)]
            return items, spoken_review.propose(kind, folders, items), images

        try:
            items, proposal, images = await asyncio.to_thread(analyze)
        except Exception as exc:
            await self._fail(task_id, exc)
            return
        duration = sum(i.duration_ms for i in items)
        candidates, lookup = await self._look_up(
            kind, proposal.title, proposal.author or None, duration, len(items)
        )
        async with self._db.session() as session:
            await session.execute(
                update(ImportTask)
                .where(ImportTask.id == task_id)
                .values(
                    status=PENDING,
                    items=[i.to_json() for i in items],
                    candidates=candidates,
                    recommendation=None,
                    spoken={
                        "kind": kind,
                        "folders": [str(f) for f in folders],
                        "images": images,
                        "proposal": proposal.to_json(),
                        "lookup": lookup,
                    },
                )
            )
            await session.commit()

    async def _apply_spoken(self, task_id: int) -> None:
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
            if task is None or task.spoken is None or task.decision is None:
                return
            kind = task.spoken["kind"]
            metadata = spoken_review.SpokenMetadata.from_json(task.decision["metadata"])
            # Selected files (not folders): nothing around them is removed after a move.
            whole_folders = not any(files.is_audio(Path(f)) for f in task.spoken["folders"])
            folder = await music_folders.get_folder(session, SPOKEN_FOLDERS[kind])
            task.status = APPLYING
            await session.commit()
        if folder is None:
            message = f"No {SPOKEN_FOLDERS[kind]} folder configured (Settings → Library)"
            await self._fail(task_id, TaggerError(message), keep_pending=True)
            return
        settings = await self._import_settings()
        root = Path(folder.path)
        try:
            cover = await self._cover_image(metadata.cover)
            placed = await asyncio.to_thread(
                spoken_review.place,
                kind,
                metadata,
                root,
                move=settings.mode == "move",
                cover=cover,
                remove_emptied=whole_folders,
            )
        except TaggerError as exc:
            await self._fail(task_id, exc, keep_pending=True)  # fixable in the review
            return
        except Exception as exc:
            await self._fail(task_id, exc, keep_pending=True)
            return
        relative = placed.folder.relative_to(root).as_posix()
        await self._scans.scan_paths(folder.id, [relative])
        async with self._db.session() as session:
            await session.execute(
                update(ImportTask)
                .where(ImportTask.id == task_id)
                .values(
                    status=IMPORTED,
                    error=None,
                    result={
                        "folder": relative,
                        "paths": [p.relative_to(root).as_posix() for p in placed.files],
                        "skipped": placed.skipped,
                    },
                )
            )
            await session.commit()

    async def _cover_image(self, cover: str | None) -> tuple[bytes, str] | None:
        """The chosen cover's image: from the files, or downloaded (best effort: a cover
        that cannot be downloaded does not stop the import)."""
        if not cover:
            return None
        if not cover.startswith("url:"):
            return await asyncio.to_thread(spoken_review.picture, cover)
        if self._http is None:
            return None
        try:
            response = await self._http().get(cover.removeprefix("url:"))
        except httpx.HTTPError:
            logger.warning("Cannot download the cover %s", cover)
            return None
        mime = response.headers.get("content-type", "").split(";")[0].strip()
        if response.status_code != 200 or not mime.startswith("image/"):
            return None
        if len(response.content) > MAX_COVER_BYTES:
            return None
        return response.content, mime

    async def forget(self, paths: list[Path], library_root: Path) -> None:
        """Tells the tagger that library files were deleted (in its thread, like every
        tagger call)."""
        await self._in_thread(self.tagger.forget, paths, library_root)

    # --- worker ---------------------------------------------------------------------

    async def _work(self) -> None:
        handlers: dict[str, Callable[[int], Any]] = {
            "job": self._run_job,
            "identify": self._identify_task,
            "identify_spoken": self._identify_spoken,
            "apply": self._apply_task,
            "apply_spoken": self._apply_spoken,
            "search": self._search_task,
        }
        while True:
            _, _, kind, item_id = await self._queue.get()
            self._working = True
            try:
                await handlers[kind](item_id)
            except Exception:
                logger.exception("Import work %s %s failed", kind, item_id)
            finally:
                self._working = False
                self._queue.task_done()

    async def call_tagger[T](self, function: Callable[..., T], *args: Any) -> T:
        """Runs a tagger method in the tagger thread (e.g. `tagger.library`)."""
        return await self._in_thread(function, *args)

    async def _in_thread[T](self, function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: function(*args, **kwargs))

    async def _run_job(self, job_id: int) -> None:
        async with self._db.session() as session:
            job = await session.get(ImportJob, job_id)
            if job is None:
                return
            job.status, job.started_at = "running", _now()
            await session.commit()
            sources = [Path(s) for s in job.sources]
            kind = job.kind
        if kind in SPOKEN_FOLDERS:
            await self._run_spoken_job(job_id, sources, kind)
            return
        try:
            folders: list[Path] = []
            for source in sources:
                folders += await self._in_thread(files.find_album_folders, source)
            async with self._db.session() as session:
                tasks = [
                    ImportTask(job_id=job_id, source_dir=str(f), status=QUEUED) for f in folders
                ]
                session.add_all(tasks)
                await session.commit()
                task_ids = [t.id for t in tasks]
            for task_id in task_ids:
                await self._identify_task(task_id)
            status, error = "done", None if folders else "No audio files found"
        except Exception as exc:
            logger.exception("Import job %s failed", job_id)
            status, error = "failed", str(exc)
        async with self._db.session() as session:
            await session.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id)
                .values(status=status, error=error, finished_at=_now())
            )
            await session.commit()

    async def _identify_task(self, task_id: int) -> None:
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
            if task is None:
                return
            task.status = ANALYZING
            await session.commit()
            source = Path(task.source_dir)
        try:
            items = await self._in_thread(files.read_items, source)
            if not items:
                raise TaggerError("No readable audio files in this folder")
            identification = await self._in_thread(self.tagger.identify, items)
        except Exception as exc:
            await self._fail(task_id, exc)
            return
        await self._store_identification(task_id, items, identification)

        settings = await self._import_settings()
        best = identification.candidates[0] if identification.candidates else None
        if (
            settings.auto_apply_strong
            and best
            and identification.recommendation is Recommendation.STRONG
        ):
            async with self._db.session() as session:
                await session.execute(
                    update(ImportTask)
                    .where(ImportTask.id == task_id)
                    .values(
                        status=QUEUED,
                        decision={"action": "apply", "candidateId": best.id, "auto": True},
                    )
                )
                await session.commit()
            await self._apply_task(task_id)

    async def _search_task(self, task_id: int) -> None:
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
            if task is None or task.decision is None:
                return
            task.status = ANALYZING
            await session.commit()
            query = dict(task.decision)
            items = [ItemInfo.from_json(i) for i in task.items]
        try:
            identification = await self._in_thread(
                self.tagger.search,
                items,
                artist=query.get("artist"),
                album=query.get("album"),
                release_id=query.get("releaseId"),
            )
        except Exception as exc:
            await self._fail(task_id, exc, keep_pending=True)
            return
        await self._store_identification(task_id, items, identification)

    async def _apply_task(self, task_id: int) -> None:
        async with self._db.session() as session:
            task = await session.get(ImportTask, task_id)
            if task is None or task.decision is None:
                return
            decision = dict(task.decision)
            items = [ItemInfo.from_json(i) for i in task.items]
            candidate = None
            if decision.get("action") == "apply":
                data = next(
                    (c for c in task.candidates if c["id"] == decision["candidateId"]), None
                )
                candidate = Candidate.from_json(data) if data else None
            folder = await music_folders.get_library(session)
            job = await session.get(ImportJob, task.job_id)
            adopt = job is not None and job.kind == ADOPT
            # An adopted album is in the library by definition: no duplicate to look for.
            existing = None if adopt else await duplicates.find_existing(session, items, candidate)
            task.status = APPLYING
            await session.commit()
        if folder is None:
            await self._fail(task_id, TaggerError("No library folder configured (Settings)"), True)
            return
        if existing is not None:
            message = f"This album is already in the library: {existing}. "
            message += "Delete that album first, or skip this one."
            await self._fail(task_id, TaggerError(message), keep_pending=True)
            return
        settings = await self._import_settings()
        mode = ImportMode.IN_PLACE if adopt else ImportMode(settings.mode)
        options = ImportOptions(mode=mode)
        root = Path(folder.path)
        staging = self._staging_root / f"task-{task_id}"
        converted = 0
        try:
            lossless = any(transcode.is_lossless(i) for i in items)
            # Adopted files stay as they are (no conversion inside the library).
            if not adopt and settings.transcode_lossless and lossless:
                await self._set_status(task_id, CONVERTING)
                items, converted = await transcode.convert_lossless(items, staging)
                await self._set_status(task_id, APPLYING)
            imported = await self._in_thread(self.tagger.apply, items, candidate, root, options)
        except TaggerError as exc:
            # Fixable by the admin (e.g. already in the library): back to review.
            await self._fail(task_id, exc, keep_pending=True)
            return
        except Exception as exc:
            await self._fail(task_id, exc)
            return
        finally:
            await transcode.clean_staging(staging)
        # The album is in the library pages as soon as the task shows "imported".
        album_dirs = sorted({p.parent.relative_to(root).as_posix() for p in imported})
        await self._scans.scan_paths(folder.id, album_dirs)
        async with self._db.session() as session:
            await session.execute(
                update(ImportTask)
                .where(ImportTask.id == task_id)
                .values(
                    status=IMPORTED,
                    error=None,
                    result={
                        "paths": [p.relative_to(root).as_posix() for p in imported],
                        "converted": converted,
                    },
                )
            )
            await session.commit()

    async def _set_status(self, task_id: int, status: str) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(ImportTask).where(ImportTask.id == task_id).values(status=status)
            )
            await session.commit()

    # --- helpers --------------------------------------------------------------------

    async def _store_identification(
        self, task_id: int, items: list[ItemInfo], identification: Identification
    ) -> None:
        async with self._db.session() as session:
            await session.execute(
                update(ImportTask)
                .where(ImportTask.id == task_id)
                .values(
                    status=PENDING,
                    items=[i.to_json() for i in items],
                    candidates=[c.to_json() for c in identification.candidates],
                    recommendation=identification.recommendation.value,
                )
            )
            await session.commit()

    async def _fail(self, task_id: int, error: Exception, keep_pending: bool = False) -> None:
        if not isinstance(error, TaggerError):
            logger.exception("Import task %s failed", task_id, exc_info=error)
        async with self._db.session() as session:
            await session.execute(
                update(ImportTask)
                .where(ImportTask.id == task_id)
                .values(status=PENDING if keep_pending else FAILED, error=str(error))
            )
            await session.commit()

    async def _import_settings(self) -> server_settings.ImportSettings:
        async with self._db.session() as session:
            return await server_settings.get_import_settings(session)


async def list_jobs(db: Database, limit: int = 20) -> list[tuple[ImportJob, list[ImportTask]]]:
    async with db.session() as session:
        jobs = (
            await session.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(limit))
        ).all()
        tasks = (
            await session.scalars(
                select(ImportTask)
                .where(ImportTask.job_id.in_([j.id for j in jobs]))
                .order_by(ImportTask.id)
            )
        ).all()
    by_job: dict[int, list[ImportTask]] = {}
    for task in tasks:
        by_job.setdefault(task.job_id, []).append(task)
    return [(job, by_job.get(job.id, [])) for job in jobs]


def _ranked(found: list[books.BookCandidate], duration_ms: int) -> list[books.BookCandidate]:
    """A catalog's candidates, the editions lasting about as long as the files first (the
    catalog's own order otherwise)."""
    if not duration_ms:
        return found

    def distance(candidate: books.BookCandidate) -> float:
        if not candidate.duration_ms:
            return 1.0  # unknown: after the editions within 100 % of the files' duration
        return abs(candidate.duration_ms - duration_ms) / duration_ms

    return sorted(found, key=distance)
