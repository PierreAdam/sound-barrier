"""Subsonic response models. Field names are snake_case and serialized as camelCase."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SubsonicModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- system ---------------------------------------------------------------


class License(SubsonicModel):
    valid: bool


class OpenSubsonicExtension(SubsonicModel):
    name: str
    versions: list[int]


class ScanStatus(SubsonicModel):
    scanning: bool
    count: int | None = None
    last_scan: datetime | None = None  # OpenSubsonic


# --- browsing -------------------------------------------------------------


class MusicFolder(SubsonicModel):
    id: int
    name: str | None = None


class MusicFolders(SubsonicModel):
    music_folder: list[MusicFolder] = Field(default_factory=list[MusicFolder])


class ArtistID3(SubsonicModel):
    id: str
    name: str
    cover_art: str | None = None
    artist_image_url: str | None = None
    album_count: int
    starred: datetime | None = None
    user_rating: int | None = None  # OpenSubsonic
    music_brainz_id: str | None = None  # OpenSubsonic
    sort_name: str | None = None  # OpenSubsonic


class IndexID3(SubsonicModel):
    name: str
    artist: list[ArtistID3] = Field(default_factory=list[ArtistID3])


class ArtistsID3(SubsonicModel):
    ignored_articles: str
    index: list[IndexID3] = Field(default_factory=list[IndexID3])


# OpenSubsonic building blocks


class ItemGenre(SubsonicModel):
    name: str


class ArtistRef(SubsonicModel):
    id: str
    name: str


class Contributor(SubsonicModel):
    role: str
    sub_role: str | None = None
    artist: ArtistRef


class ReplayGain(SubsonicModel):
    track_gain: float | None = None
    album_gain: float | None = None
    track_peak: float | None = None
    album_peak: float | None = None


class ItemDate(SubsonicModel):
    year: int | None = None
    month: int | None = None
    day: int | None = None


class DiscTitle(SubsonicModel):
    disc: int
    title: str


class RecordLabel(SubsonicModel):
    name: str


class Child(SubsonicModel):
    """A song (Subsonic `Child` with isDir=false)."""

    id: str
    parent: str | None = None
    is_dir: bool = False
    title: str
    album: str | None = None
    artist: str | None = None
    track: int | None = None
    year: int | None = None
    genre: str | None = None
    cover_art: str | None = None
    size: int | None = None
    content_type: str | None = None
    suffix: str | None = None
    duration: int | None = None  # seconds
    bit_rate: int | None = None
    path: str | None = None
    disc_number: int | None = None
    created: datetime | None = None
    album_id: str | None = None
    artist_id: str | None = None
    type: str = "music"
    starred: datetime | None = None
    user_rating: int | None = None
    play_count: int | None = None
    played: datetime | None = None
    # OpenSubsonic
    bit_depth: int | None = None
    sampling_rate: int | None = None
    channel_count: int | None = None
    media_type: str = "song"
    music_brainz_id: str | None = None
    genres: list[ItemGenre] = Field(default_factory=list[ItemGenre])
    artists: list[ArtistRef] = Field(default_factory=list[ArtistRef])
    display_artist: str | None = None
    album_artists: list[ArtistRef] = Field(default_factory=list[ArtistRef])
    display_album_artist: str | None = None
    contributors: list[Contributor] = Field(default_factory=list[Contributor])
    display_composer: str | None = None
    bpm: int | None = None
    comment: str | None = None
    sort_name: str | None = None
    explicit_status: str | None = None
    replay_gain: ReplayGain | None = None


class AlbumID3(SubsonicModel):
    id: str
    name: str
    artist: str | None = None
    artist_id: str | None = None
    cover_art: str | None = None
    song_count: int
    duration: int  # seconds
    play_count: int | None = None
    created: datetime
    starred: datetime | None = None
    year: int | None = None
    genre: str | None = None
    user_rating: int | None = None
    # OpenSubsonic
    played: datetime | None = None  # last played by the user
    record_labels: list[RecordLabel] = Field(default_factory=list[RecordLabel])
    music_brainz_id: str | None = None
    genres: list[ItemGenre] = Field(default_factory=list[ItemGenre])
    artists: list[ArtistRef] = Field(default_factory=list[ArtistRef])
    display_artist: str | None = None
    release_types: list[str] = Field(default_factory=list[str])
    moods: list[str] = Field(default_factory=list[str])
    sort_name: str | None = None
    original_release_date: ItemDate | None = None
    release_date: ItemDate | None = None
    is_compilation: bool = False
    explicit_status: str | None = None
    disc_titles: list[DiscTitle] = Field(default_factory=list[DiscTitle])


class AlbumWithSongsID3(AlbumID3):
    song: list[Child] = Field(default_factory=list[Child])


class ArtistWithAlbumsID3(ArtistID3):
    album: list[AlbumID3] = Field(default_factory=list[AlbumID3])


class AlbumList2(SubsonicModel):
    album: list[AlbumID3] = Field(default_factory=list[AlbumID3])


class ArtistInfo2(SubsonicModel):
    biography: str | None = None
    music_brainz_id: str | None = None
    last_fm_url: str | None = None
    small_image_url: str | None = None
    medium_image_url: str | None = None
    large_image_url: str | None = None
    similar_artist: list[ArtistID3] = Field(default_factory=list[ArtistID3])


class TopSongs(SubsonicModel):
    song: list[Child] = Field(default_factory=list[Child])


# --- folder browsing ---------------------------------------------------------


class Artist(SubsonicModel):
    """A directory of the index (getIndexes, search2)."""

    id: str
    name: str
    starred: datetime | None = None
    user_rating: int | None = None


class Index(SubsonicModel):
    name: str
    artist: list[Artist] = Field(default_factory=list[Artist])


class Indexes(SubsonicModel):
    last_modified: int  # milliseconds since the epoch
    ignored_articles: str
    index: list[Index] = Field(default_factory=list[Index])
    child: list[Child] = Field(default_factory=list[Child])  # songs directly in a root


class Directory(SubsonicModel):
    id: str
    parent: str | None = None
    name: str
    starred: datetime | None = None
    user_rating: int | None = None
    play_count: int | None = None
    child: list[Child] = Field(default_factory=list[Child])


class AlbumList(SubsonicModel):
    album: list[Child] = Field(default_factory=list[Child])  # album directories


class SearchResult2(SubsonicModel):
    artist: list[Artist] = Field(default_factory=list[Artist])
    album: list[Child] = Field(default_factory=list[Child])
    song: list[Child] = Field(default_factory=list[Child])


# --- stars, genres, random songs, now playing ---------------------------------


class Starred2(SubsonicModel):
    artist: list[ArtistID3] = Field(default_factory=list[ArtistID3])
    album: list[AlbumID3] = Field(default_factory=list[AlbumID3])
    song: list[Child] = Field(default_factory=list[Child])


class Starred(SubsonicModel):
    artist: list[Artist] = Field(default_factory=list[Artist])
    album: list[Child] = Field(default_factory=list[Child])
    song: list[Child] = Field(default_factory=list[Child])


class Songs(SubsonicModel):
    """randomSongs, songsByGenre."""

    song: list[Child] = Field(default_factory=list[Child])


class Genre(SubsonicModel):
    value: str  # the name (element text in XML)
    song_count: int
    album_count: int


class Genres(SubsonicModel):
    genre: list[Genre] = Field(default_factory=list[Genre])


class NowPlayingEntry(Child):
    username: str
    minutes_ago: int
    player_id: int
    player_name: str | None = None


class NowPlaying(SubsonicModel):
    entry: list[NowPlayingEntry] = Field(default_factory=list[NowPlayingEntry])


# --- the apps' play queue ---------------------------------------------------


class PlayQueue(SubsonicModel):
    current: str | None = None  # song id
    position: int | None = None  # milliseconds into the current song
    username: str
    changed: datetime
    changed_by: str
    entry: list[Child] = Field(default_factory=list[Child])


class PlayQueueByIndex(SubsonicModel):
    current_index: int | None = None
    position: int | None = None
    username: str
    changed: datetime
    changed_by: str
    entry: list[Child] = Field(default_factory=list[Child])


# --- playlists ---------------------------------------------------------------


class Playlist(SubsonicModel):
    id: str
    name: str
    comment: str | None = None
    owner: str
    public: bool
    song_count: int
    duration: int  # seconds
    created: datetime
    changed: datetime
    cover_art: str | None = None


class PlaylistWithSongs(Playlist):
    entry: list[Child] = Field(default_factory=list[Child])


class Playlists(SubsonicModel):
    playlist: list[Playlist] = Field(default_factory=list[Playlist])


class SearchResult3(SubsonicModel):
    artist: list[ArtistID3] = Field(default_factory=list[ArtistID3])
    album: list[AlbumID3] = Field(default_factory=list[AlbumID3])
    song: list[Child] = Field(default_factory=list[Child])


# --- users ----------------------------------------------------------------


class User(SubsonicModel):
    username: str
    email: str | None = None
    scrobbling_enabled: bool
    max_bit_rate: int | None = None
    admin_role: bool
    settings_role: bool
    download_role: bool
    upload_role: bool
    playlist_role: bool
    cover_art_role: bool
    comment_role: bool
    podcast_role: bool
    stream_role: bool
    jukebox_role: bool
    share_role: bool
    video_conversion_role: bool
    folder: list[int] = Field(default_factory=list[int])


class Users(SubsonicModel):
    user: list[User] = Field(default_factory=list[User])
