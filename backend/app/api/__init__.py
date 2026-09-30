"""Our own JSON API (`/api`), used by the web UI (and the transcription workers,
`api/transcripts.py`) for what Subsonic does not cover."""

from fastapi import APIRouter

from app.api import (
    about,
    auth,
    covers,
    discography,
    external,
    library,
    lyrics,
    manage,
    new_releases,
    players,
    plugins,
    preferences,
    queue,
    remote,
    server_player,
    spoken,
    tags,
    transcripts,
)


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(about.router)
    router.include_router(auth.router)
    router.include_router(library.router)
    router.include_router(lyrics.router)
    router.include_router(manage.router)
    router.include_router(new_releases.router)
    router.include_router(preferences.router)
    router.include_router(queue.router)
    router.include_router(players.router)
    router.include_router(remote.router)
    router.include_router(server_player.router)
    router.include_router(spoken.router)
    router.include_router(external.router)
    router.include_router(covers.router)
    router.include_router(discography.router)
    router.include_router(plugins.router)
    router.include_router(tags.router)
    router.include_router(transcripts.worker_router)
    router.include_router(transcripts.admin_router)
    return router
