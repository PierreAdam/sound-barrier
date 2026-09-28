"""Our own JSON API (`/api`), used only by the web UI, for what Subsonic does not cover."""

from fastapi import APIRouter

from app.api import auth, covers, external, library, manage, preferences, queue, tags


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(auth.router)
    router.include_router(library.router)
    router.include_router(manage.router)
    router.include_router(preferences.router)
    router.include_router(queue.router)
    router.include_router(external.router)
    router.include_router(covers.router)
    router.include_router(tags.router)
    return router
