from fastapi import APIRouter


def build_router() -> APIRouter:
    # Importing the endpoint modules registers their handlers.
    from app.subsonic.endpoints import (
        annotation,
        bookmarks,
        browsing,
        folders,
        info,
        lists,
        lyrics,
        media,
        playlists,
        podcasts,
        queue,
        scanning,
        system,
        users,
    )
    from app.subsonic.router import registry

    _ = (
        annotation,
        bookmarks,
        browsing,
        folders,
        info,
        lists,
        lyrics,
        media,
        playlists,
        podcasts,
        queue,
        scanning,
        system,
        users,
    )

    return registry.build_router()
