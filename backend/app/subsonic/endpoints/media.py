"""Binary endpoints: audio (stream, download) and images (getCoverArt).

Errors still use the Subsonic envelope; successful responses are raw bytes.
"""

import hashlib
from pathlib import Path

from starlette.responses import FileResponse, Response

from app.core.config import Settings
from app.services import media
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry


async def _audio(ctx: SubsonicContext) -> media.AudioFile:
    audio = await media.song_file(ctx.session, ctx.user, ctx.params.require("id"))
    if audio is None:
        raise SubsonicError.not_found("Song")
    return audio


@registry.endpoint("stream")
async def stream(ctx: SubsonicContext) -> Response:
    if not ctx.user.stream_role:
        raise SubsonicError.not_authorized("Streaming is not allowed for this user")
    audio = await _audio(ctx)
    # No transcoding yet: `format` and `maxBitRate` are ignored and the original file is
    # sent. FileResponse handles Range requests (seeking).
    return FileResponse(audio.path, media_type=audio.song.content_type)


@registry.endpoint("download")
async def download(ctx: SubsonicContext) -> Response:
    if not ctx.user.download_role:
        raise SubsonicError.not_authorized("Downloading is not allowed for this user")
    audio = await _audio(ctx)
    return FileResponse(
        audio.path, media_type=audio.song.content_type, filename=Path(audio.song.path).name
    )


@registry.endpoint("getCoverArt")
async def get_cover_art(ctx: SubsonicContext) -> Response:
    settings: Settings = ctx.request.app.state.settings
    image = await media.cover_image(
        ctx.session,
        ctx.params.require("id"),
        ctx.params.get_int("size"),
        settings.data_dir / "cache" / "covers",
        settings.data_dir / "artist-pictures",
    )
    if image is None:
        raise SubsonicError.not_found("Cover art")
    # Covers can change (an admin chooses a new one) under the same id: browsers keep
    # them but ask again each time, and get "304 Not Modified" while they are the same.
    etag = f'"{hashlib.sha1(image.data).hexdigest()[:20]}"'
    headers = {"Cache-Control": "private, no-cache", "ETag": etag}
    if ctx.request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(image.data, media_type=image.content_type, headers=headers)
