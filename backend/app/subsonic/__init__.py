from fastapi import APIRouter


def build_router() -> APIRouter:
    # Importing the endpoint modules registers their handlers.
    from app.subsonic.endpoints import (
        annotation,
        browsing,
        folders,
        info,
        lists,
        lyrics,
        media,
        playlists,
        queue,
        scanning,
        system,
        users,
    )
    from app.subsonic.router import registry

    _ = (
        annotation,
        browsing,
        folders,
        info,
        lists,
        lyrics,
        media,
        playlists,
        queue,
        scanning,
        system,
        users,
    )

    return registry.build_router()
