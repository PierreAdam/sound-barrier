"""Bookmarks: getBookmarks, createBookmark, deleteBookmark (services/bookmarks.py)."""

from app.services import bookmarks, browsing
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry


@registry.endpoint("getBookmarks")
async def get_bookmarks(ctx: SubsonicContext) -> Payload:
    found = await bookmarks.list_for(ctx.session, ctx.user)
    return {
        "bookmarks": schemas.Bookmarks(
            bookmark=[
                schemas.BookmarkItem(
                    position=entry.bookmark.position_ms,
                    username=ctx.user.username,
                    comment=entry.bookmark.comment,
                    created=entry.bookmark.created_at,
                    changed=entry.bookmark.changed_at,
                    entry=mappers.song(entry.song),
                )
                for entry in found
            ]
        )
    }


@registry.endpoint("createBookmark")
async def create_bookmark(ctx: SubsonicContext) -> Payload:
    """`position` in milliseconds; an existing bookmark of the song is moved."""
    song_id = browsing.parse_id(ctx.params.require("id"))
    position = ctx.params.require_int("position")
    if song_id is None or not await bookmarks.save(
        ctx.session, ctx.user, song_id, position, ctx.params.get("comment"), ctx.client
    ):
        raise SubsonicError.not_found("Song")
    return None


@registry.endpoint("deleteBookmark")
async def delete_bookmark(ctx: SubsonicContext) -> Payload:
    song_id = browsing.parse_id(ctx.params.require("id"))
    if song_id is None:
        raise SubsonicError.not_found("Song")
    await bookmarks.remove(ctx.session, ctx.user, song_id)
    return None
