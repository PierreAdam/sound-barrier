"""Podcasts and audiobooks for Subsonic apps: both are served as podcasts (a show or a
book is a channel, its episodes / chapters are episodes), from their own library folders
(services/spoken.py). RSS subscriptions are not supported: the files are local."""

from app.services import browsing, music_folders, spoken
from app.services.browsing import SongEntry
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry

NO_SUBSCRIPTIONS = "Podcast subscriptions (RSS) are not supported: podcasts are local files"


def _episode(show: spoken.Show, entry: SongEntry) -> schemas.PodcastEpisode:
    child = mappers.song(entry)
    return schemas.PodcastEpisode(
        **child.model_dump(),
        stream_id=child.id,
        channel_id=str(show.album.id),
        description=entry.song.comment,
        publish_date=entry.song.file_mtime,
    )


def _channel(show: spoken.Show, with_episodes: bool) -> schemas.PodcastChannel:
    album = show.album
    kind = "Audiobook" if show.kind == music_folders.AUDIOBOOKS else "Podcast"
    return schemas.PodcastChannel(
        id=str(album.id),
        title=album.name,
        description=f"{kind} · {album.display_artist}" if album.display_artist else kind,
        cover_art=str(album.artwork_id) if album.artwork_id else None,
        episode=[_episode(show, e) for e in show.episodes] if with_episodes else [],
    )


@registry.endpoint("getPodcasts")
async def get_podcasts(ctx: SubsonicContext) -> Payload:
    with_episodes = ctx.params.get_bool("includeEpisodes", True)
    channel_id = ctx.params.get("id")
    album_id = browsing.parse_id(channel_id) if channel_id else None
    if channel_id and album_id is None:
        raise SubsonicError.not_found("Podcast channel")
    found = await spoken.shows(ctx.session, ctx.user, album_id=album_id)
    if channel_id and not found:
        raise SubsonicError.not_found("Podcast channel")
    return {"podcasts": schemas.Podcasts(channel=[_channel(s, with_episodes) for s in found])}


@registry.endpoint("getNewestPodcasts")
async def get_newest_podcasts(ctx: SubsonicContext) -> Payload:
    count = min(max(ctx.params.get_int("count", 20) or 0, 0), 500)
    found = await spoken.newest_episodes(ctx.session, ctx.user, count)
    return {"newestPodcasts": schemas.NewestPodcasts(episode=[_episode(s, e) for s, e in found])}


@registry.endpoint("getPodcastEpisode")
async def get_podcast_episode(ctx: SubsonicContext) -> Payload:
    """OpenSubsonic."""
    song_id = browsing.parse_id(ctx.params.require("id"))
    entry = await browsing.get_song(ctx.session, ctx.user, song_id) if song_id else None
    show = await spoken.show(ctx.session, ctx.user, entry.album.id) if entry else None
    if entry is None or show is None:
        raise SubsonicError.not_found("Podcast episode")
    return {"podcastEpisode": _episode(show, entry)}


def _unsupported(name: str) -> None:
    @registry.endpoint(name)
    async def handler(ctx: SubsonicContext) -> Payload:  # pyright: ignore[reportUnusedFunction]
        raise SubsonicError(ErrorCode.GENERIC, NO_SUBSCRIPTIONS)


for _name in (
    "createPodcastChannel",
    "refreshPodcasts",
    "deletePodcastChannel",
    "deletePodcastEpisode",
    "downloadPodcastEpisode",
):
    _unsupported(_name)
