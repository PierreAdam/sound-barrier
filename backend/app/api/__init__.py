"""Our own JSON API (`/api`), used only by the web UI, for what Subsonic does not cover."""

from fastapi import APIRouter

from app.api import (
    auth,
    covers,
    discography,
    external,
    library,
    lyrics,
    manage,
    new_releases,
    plugins,
    preferences,
    queue,
    spoken,
    tags,
)


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(auth.router)
    router.include_router(library.router)
    router.include_router(lyrics.router)
    router.include_router(manage.router)
    router.include_router(new_releases.router)
    router.include_router(preferences.router)
    router.include_router(queue.router)
    router.include_router(spoken.router)
    router.include_router(external.router)
    router.include_router(covers.router)
    router.include_router(discography.router)
    router.include_router(plugins.router)
    router.include_router(tags.router)
    return router
