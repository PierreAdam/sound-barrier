"""Reads audio metadata with mutagen and maps every tag format onto one set of fields.

Each format (ID3, Vorbis comments, MP4, APEv2, ASF) is first flattened into "raw tags":
a dict of canonical lowercase keys (Picard / Vorbis naming, e.g. `albumartist`,
`musicbrainz_albumid`) to lists of strings. `TrackTags` is then built from those keys
without caring about the original format.
"""
# mutagen has no type information.
# pyright: basic

import base64
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mutagen
from mutagen.apev2 import APEv2
from mutagen.asf import ASFTags
from mutagen.flac import Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4Cover, MP4Tags

logger = logging.getLogger(__name__)

type RawTags = dict[str, list[str]]

# --- format mappings ------------------------------------------------------

# Free-form keys (Vorbis, ID3 TXXX, MP4 freeform, APE, ASF) -> canonical key.
_ALIASES = {
    "album artist": "albumartist",
    "album_artist": "albumartist",
    "totaltracks": "tracktotal",
    "totaldiscs": "disctotal",
    "track": "tracknumber",
    "disc": "discnumber",
    "year": "date",
    "organization": "label",
    "publisher": "label",
    "description": "comment",
    # Audiobook series (Mp3tag, Audiobookshelf...): its name and the book's number.
    "series-part": "seriespart",
    "series_part": "seriespart",
    "seriesnumber": "seriespart",
    "movementname": "movementname",
    "unsyncedlyrics": "lyrics",
    "unsynced lyrics": "lyrics",
    "itunesadvisory": "explicit",
    "musicbrainz album id": "musicbrainz_albumid",
    "musicbrainz artist id": "musicbrainz_artistid",
    "musicbrainz album artist id": "musicbrainz_albumartistid",
    "musicbrainz release group id": "musicbrainz_releasegroupid",
    "musicbrainz release track id": "musicbrainz_releasetrackid",
    "musicbrainz track id": "musicbrainz_trackid",
    "musicbrainz album type": "releasetype",
    "musicbrainz_albumtype": "releasetype",
}

_ID3_FRAMES = {
    "TIT2": "title",
    "TPE1": "artist",
    "TPE2": "albumartist",
    "TALB": "album",
    "TRCK": "tracknumber",
    "TPOS": "discnumber",
    "TDRC": "date",
    "TDOR": "originaldate",
    "TDRL": "releasedate",
    "TCOM": "composer",
    "TEXT": "lyricist",
    "TPE3": "conductor",
    "TPE4": "remixer",
    "TBPM": "bpm",
    "TCMP": "compilation",
    "TPUB": "label",
    "TSOT": "titlesort",
    "TSOP": "artistsort",
    "TSO2": "albumartistsort",
    "TSOA": "albumsort",
    "TSOC": "composersort",
    "TMOO": "mood",
    "TSST": "discsubtitle",
    "TIT1": "grouping",  # also where the import writes an audiobook's series
    "GRP1": "grouping",
    "MVNM": "movementname",  # audiobook series (Mp3tag's convention)
    "MVIN": "movement",
}

# ID3 TIPL (involved people) roles we keep, mapped to contributor roles.
_ID3_TIPL_ROLES = {
    "arranger": "arranger",
    "producer": "producer",
    "engineer": "engineer",
    "mix": "mixer",
    "dj-mix": "djmixer",
}

_MP4_ATOMS = {
    "\xa9nam": "title",
    "\xa9ART": "artist",
    "aART": "albumartist",
    "\xa9alb": "album",
    "\xa9day": "date",
    "\xa9gen": "genre",
    "\xa9wrt": "composer",
    "\xa9cmt": "comment",
    "\xa9lyr": "lyrics",
    "\xa9grp": "grouping",
    "\xa9mvn": "movementname",  # audiobook series (M4B tools' convention)
    "sonm": "titlesort",
    "soar": "artistsort",
    "soaa": "albumartistsort",
    "soal": "albumsort",
    "soco": "composersort",
}
_MP4_FREEFORM_PREFIX = "----:com.apple.iTunes:"

_ASF_ATTRIBUTES = {
    "title": "title",
    "author": "artist",
    "wm/albumartist": "albumartist",
    "wm/albumtitle": "album",
    "wm/tracknumber": "tracknumber",
    "wm/partofset": "discnumber",
    "wm/year": "date",
    "wm/originalreleaseyear": "originaldate",
    "wm/genre": "genre",
    "wm/composer": "composer",
    "wm/writer": "lyricist",
    "wm/conductor": "conductor",
    "wm/beatsperminute": "bpm",
    "wm/publisher": "label",
    "wm/mood": "mood",
    "wm/lyrics": "lyrics",
    "wm/contentgroupdescription": "grouping",
    "wm/artistsortorder": "artistsort",
    "wm/albumartistsortorder": "albumartistsort",
    "wm/albumsortorder": "albumsort",
    "wm/titlesortorder": "titlesort",
}

CONTRIBUTOR_ROLES = (
    "composer",
    "lyricist",
    "conductor",
    "arranger",
    "producer",
    "engineer",
    "mixer",
    "remixer",
    "djmixer",
)


def _canonical(key: str) -> str:
    key = key.casefold().strip()
    return _ALIASES.get(key, key)


def _add(raw: RawTags, key: str, values: Any) -> None:
    if isinstance(values, str | bytes):
        values = [values]
    for value in values:
        text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
        raw.setdefault(key, []).append(text)


def _raw_id3(tags: ID3) -> tuple[RawTags, bool]:
    raw: RawTags = {}
    has_picture = False
    for frame in tags.values():
        frame_id = frame.FrameID
        if frame_id in _ID3_FRAMES:
            _add(raw, _ID3_FRAMES[frame_id], frame.text)
        elif frame_id == "TCON":
            _add(raw, "genre", frame.genres)
        elif frame_id == "TXXX":
            _add(raw, _canonical(frame.desc), frame.text)
        elif frame_id == "COMM" and frame.desc == "":
            _add(raw, "comment", frame.text)
        elif frame_id == "USLT":
            _add(raw, "lyrics", frame.text)
        elif frame_id == "UFID" and frame.owner == "http://musicbrainz.org":
            _add(raw, "musicbrainz_trackid", frame.data)
        elif frame_id == "TIPL":
            for role, name in frame.people:
                if role.casefold() in _ID3_TIPL_ROLES:
                    _add(raw, _ID3_TIPL_ROLES[role.casefold()], name)
        elif frame_id == "TMCL":
            for instrument, name in frame.people:
                _add(raw, f"performer:{instrument.casefold()}", name)
        elif frame_id == "APIC":
            has_picture = True
    return raw, has_picture


def _raw_mp4(tags: MP4Tags) -> tuple[RawTags, bool]:
    raw: RawTags = {}
    for key, values in tags.items():
        if key in _MP4_ATOMS:
            _add(raw, _MP4_ATOMS[key], values)
        elif key in ("trkn", "disk"):
            number, total = values[0] if values else (0, 0)
            prefix = "track" if key == "trkn" else "disc"
            if number:
                _add(raw, f"{prefix}number", str(number))
            if total:
                _add(raw, f"{prefix}total", str(total))
        elif key == "tmpo":
            _add(raw, "bpm", [str(v) for v in values])
        elif key == "\xa9mvi":  # the series number of an audiobook (an integer atom)
            _add(raw, "movement", [str(v) for v in values])
        elif key == "cpil":
            _add(raw, "compilation", "1" if values else "0")
        elif key == "rtng":
            _add(raw, "explicit", [str(v) for v in values])
        elif key.startswith(_MP4_FREEFORM_PREFIX):
            _add(raw, _canonical(key[len(_MP4_FREEFORM_PREFIX) :]), [bytes(v) for v in values])
    return raw, bool(tags.get("covr"))


def _raw_apev2(tags: APEv2) -> tuple[RawTags, bool]:
    raw: RawTags = {}
    has_picture = False
    for key, value in tags.items():
        if key.casefold().startswith("cover art"):
            has_picture = True
        elif value.kind == 0:  # text (may hold several \0-separated values)
            _add(raw, _canonical(key), list(value))
    return raw, has_picture


def _raw_asf(tags: ASFTags) -> tuple[RawTags, bool]:
    raw: RawTags = {}
    has_picture = False
    for key, values in tags.items():
        folded = key.casefold()
        if folded == "wm/picture":
            has_picture = True
        elif folded in _ASF_ATTRIBUTES:
            _add(raw, _ASF_ATTRIBUTES[folded], [str(v) for v in values])
        else:
            _add(raw, _canonical(folded.replace("/", " ")), [str(v) for v in values])
    return raw, has_picture


def _raw_vorbis(audio: Any) -> tuple[RawTags, bool]:
    raw: RawTags = {}
    tags = audio.tags
    has_picture = bool(getattr(audio, "pictures", None))
    for key in tags.keys():  # noqa: SIM118 (VCommentDict iterates over pairs)
        folded = key.casefold()
        if folded == "metadata_block_picture":
            has_picture = True
        elif folded == "performer":
            for value in tags[key]:
                name, instrument = _split_performer(value)
                _add(raw, f"performer:{instrument}", name)
        else:
            _add(raw, _canonical(folded), tags[key])
    return raw, has_picture


_PERFORMER = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def _split_performer(value: str) -> tuple[str, str]:
    """Vorbis PERFORMER is "Name (instrument)"."""
    match = _PERFORMER.match(value)
    if match:
        return match.group(1), match.group(2).casefold()
    return value, ""


def _raw_tags(audio: Any) -> tuple[RawTags, bool]:
    tags = audio.tags
    if tags is None:
        return {}, bool(getattr(audio, "pictures", None))
    if isinstance(tags, ID3):
        return _raw_id3(tags)
    if isinstance(tags, MP4Tags):
        return _raw_mp4(tags)
    if isinstance(tags, APEv2):
        return _raw_apev2(tags)
    if isinstance(tags, ASFTags):
        return _raw_asf(tags)
    return _raw_vorbis(audio)


# --- typed result ---------------------------------------------------------


@dataclass(frozen=True)
class Contributor:
    name: str
    role: str
    sub_role: str = ""


@dataclass
class TrackTags:
    title: str | None = None
    title_sort: str | None = None
    artists: list[str] = field(default_factory=list[str])
    artist_mbz_ids: list[str] = field(default_factory=list[str])
    display_artist: str | None = None
    artist_sort: str | None = None
    album: str | None = None
    album_sort: str | None = None
    album_artists: list[str] = field(default_factory=list[str])
    album_artist_mbz_ids: list[str] = field(default_factory=list[str])
    display_album_artist: str | None = None
    album_artist_sort: str | None = None
    track_number: int | None = None
    track_total: int | None = None
    disc_number: int | None = None
    disc_total: int | None = None
    disc_subtitle: str | None = None
    date: str | None = None  # partial ISO date
    original_date: str | None = None
    release_date: str | None = None
    genres: list[str] = field(default_factory=list[str])
    contributors: list[Contributor] = field(default_factory=list[Contributor])
    bpm: int | None = None
    comment: str | None = None
    grouping: str | None = None
    # Audiobooks: the series and the book's number in it (see series_of).
    series: str | None = None
    series_number: str | None = None
    compilation: bool = False
    labels: list[str] = field(default_factory=list[str])
    release_types: list[str] = field(default_factory=list[str])
    moods: list[str] = field(default_factory=list[str])
    explicit_status: str | None = None
    mbz_recording_id: str | None = None
    mbz_track_id: str | None = None
    mbz_album_id: str | None = None
    mbz_release_group_id: str | None = None
    replaygain_track_gain: float | None = None
    replaygain_track_peak: float | None = None
    replaygain_album_gain: float | None = None
    replaygain_album_peak: float | None = None
    lyrics: str | None = None
    has_picture: bool = False

    @property
    def year(self) -> int | None:
        date = self.date or self.original_date or self.release_date
        return int(date[:4]) if date else None

    @property
    def composers(self) -> list[str]:
        return [c.name for c in self.contributors if c.role == "composer"]


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int
    bit_rate: int  # kbps
    sample_rate: int | None
    bit_depth: int | None
    channels: int | None


@dataclass(frozen=True)
class Chapter:
    """A chapter inside a file (MP4 / M4B chapter list, ID3 CHAP frames)."""

    start_ms: int
    title: str


@dataclass(frozen=True)
class AudioFile:
    tags: TrackTags
    info: AudioInfo
    chapters: list[Chapter] = field(default_factory=list[Chapter])


def _values(raw: RawTags, key: str, *, split: str | None = None) -> list[str]:
    """Non-empty, stripped, de-duplicated values of a raw tag."""
    result: list[str] = []
    for value in raw.get(key, []):
        parts = value.split(split) if split else [value]
        for part in parts:
            part = part.strip()
            if part and part not in result:
                result.append(part)
    return result


def _first(raw: RawTags, key: str) -> str | None:
    values = _values(raw, key)
    return values[0] if values else None


def _number_pair(value: str | None) -> tuple[int | None, int | None]:
    """ "3/12" -> (3, 12), "03" -> (3, None)."""
    if not value:
        return None, None
    number, _, total = value.partition("/")
    return _int(number), _int(total)


def _int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value.strip()))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def _partial_date(value: str | None) -> str | None:
    """Keeps "YYYY", "YYYY-MM" or "YYYY-MM-DD" from any date-like string."""
    if not value:
        return None
    match = _DATE.match(value.strip())
    if not match:
        return None
    return "-".join(part for part in match.groups() if part)


def _explicit_status(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().casefold()
    if value in ("1", "4", "explicit"):
        return "explicit"
    if value in ("2", "clean"):
        return "clean"
    return None


def _display(tag_values: list[str], names: list[str]) -> str | None:
    """A single-valued ARTIST tag is the display form ("A feat. B"), even when a
    multi-valued ARTISTS tag lists the individual artists."""
    if len(tag_values) == 1:
        return tag_values[0]
    return " • ".join(tag_values or names) or None


# "Series, Book 3", "Series #3", "Series - Vol. 2", "Série, Tome 4" (\u2013: an en dash).
_SERIES_NUMBER = re.compile(
    r"^(?P<series>.*?)[\s,;:\-\u2013]*"
    r"(?:\bbook|\bvol(?:ume)?\.?|\btome|\bpart|#)\s*(?P<number>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def series_of(raw: RawTags) -> tuple[str | None, str | None]:
    """An audiobook's series and number: a series tag (SERIES / SERIES-PART, MP4 and ID3
    "movement" fields), else the grouping ("Series, Book 3", as the import writes it;
    "Series #3", "Series Vol. 2"...)."""
    series = _first(raw, "series") or _first(raw, "movementname")
    number = _first(raw, "seriespart") or _first(raw, "movement")
    if series:
        return series.strip(), (number or "").strip() or None
    grouping = (_first(raw, "grouping") or "").strip()
    if not grouping:
        return None, None
    found = _SERIES_NUMBER.match(grouping)
    if found and found.group("series").strip():
        return found.group("series").strip(), found.group("number")
    return grouping, None


def build_track_tags(raw: RawTags, *, has_picture: bool) -> TrackTags:
    artist_values = _values(raw, "artist")
    artists = _values(raw, "artists") or artist_values
    album_artist_values = _values(raw, "albumartist")
    album_artists = _values(raw, "albumartists") or album_artist_values

    track_number, track_total = _number_pair(_first(raw, "tracknumber"))
    disc_number, disc_total = _number_pair(_first(raw, "discnumber"))
    series, series_number = series_of(raw)

    contributors: list[Contributor] = []
    for role in CONTRIBUTOR_ROLES:
        contributors.extend(Contributor(name, role) for name in _values(raw, role))
    for key in raw:
        if key.startswith("performer:"):
            instrument = key.partition(":")[2]
            contributors.extend(
                Contributor(name, "performer", instrument) for name in _values(raw, key)
            )

    bpm = _int(_first(raw, "bpm"))
    original_date = _partial_date(_first(raw, "originaldate") or _first(raw, "originalyear"))

    return TrackTags(
        title=_first(raw, "title"),
        title_sort=_first(raw, "titlesort"),
        artists=artists,
        artist_mbz_ids=_values(raw, "musicbrainz_artistid"),
        display_artist=_display(artist_values, artists),
        artist_sort=_first(raw, "artistsort"),
        album=_first(raw, "album"),
        album_sort=_first(raw, "albumsort"),
        album_artists=album_artists,
        album_artist_mbz_ids=_values(raw, "musicbrainz_albumartistid"),
        display_album_artist=_display(album_artist_values, album_artists),
        album_artist_sort=_first(raw, "albumartistsort"),
        track_number=track_number,
        track_total=track_total or _int(_first(raw, "tracktotal")),
        disc_number=disc_number,
        disc_total=disc_total or _int(_first(raw, "disctotal")),
        disc_subtitle=_first(raw, "discsubtitle"),
        date=_partial_date(_first(raw, "date")),
        original_date=original_date,
        release_date=_partial_date(_first(raw, "releasedate")),
        genres=_values(raw, "genre", split=";"),
        contributors=contributors,
        bpm=bpm or None,
        comment=_first(raw, "comment"),
        grouping=_first(raw, "grouping"),
        series=series,
        series_number=series_number,
        compilation=(_first(raw, "compilation") or "").casefold() in ("1", "true", "yes"),
        labels=_values(raw, "label"),
        release_types=[t.casefold() for t in _values(raw, "releasetype", split=";")],
        moods=_values(raw, "mood"),
        explicit_status=_explicit_status(_first(raw, "explicit")),
        mbz_recording_id=_first(raw, "musicbrainz_trackid"),
        mbz_track_id=_first(raw, "musicbrainz_releasetrackid"),
        mbz_album_id=_first(raw, "musicbrainz_albumid"),
        mbz_release_group_id=_first(raw, "musicbrainz_releasegroupid"),
        replaygain_track_gain=_float(_first(raw, "replaygain_track_gain")),
        replaygain_track_peak=_float(_first(raw, "replaygain_track_peak")),
        replaygain_album_gain=_float(_first(raw, "replaygain_album_gain")),
        replaygain_album_peak=_float(_first(raw, "replaygain_album_peak")),
        lyrics=_first(raw, "lyrics"),
        has_picture=has_picture,
    )


def _audio_info(audio: Any, size: int) -> AudioInfo:
    info = audio.info
    length = float(getattr(info, "length", 0) or 0)
    bit_rate = int(getattr(info, "bitrate", 0) or 0)
    if not bit_rate and length:
        bit_rate = int(size * 8 / length)
    return AudioInfo(
        duration_ms=round(length * 1000),
        bit_rate=round(bit_rate / 1000),
        sample_rate=getattr(info, "sample_rate", None) or None,
        bit_depth=getattr(info, "bits_per_sample", None) or None,
        channels=getattr(info, "channels", None) or None,
    )


def _chapters(audio: Any, duration_ms: int) -> list[Chapter]:
    """The file's chapters by start, when it has at least two (a single chapter is the
    file itself). Untitled ones are numbered."""
    found: list[tuple[int, str]] = []
    try:
        if isinstance(audio.tags, ID3):
            for frame in audio.tags.getall("CHAP"):
                title = frame.sub_frames.get("TIT2")
                found.append((int(frame.start_time), str(title.text[0]) if title else ""))
        elif getattr(audio, "chapters", None):
            found = [(round(c.start * 1000), c.title or "") for c in audio.chapters]
    except Exception as error:  # a damaged chapter list: the file still plays
        logger.warning("Cannot read the chapters of %s: %s", audio.filename, error)
        return []
    starts: dict[int, str] = {}
    for start, title in sorted(found):
        if 0 <= start < max(duration_ms, 1):
            starts.setdefault(start, title.strip())
    if len(starts) < 2:
        return []
    return [
        Chapter(start, title or f"Chapter {i}")
        for i, (start, title) in enumerate(starts.items(), 1)
    ]


def read_audio_file(path: Path) -> AudioFile | None:
    """Returns None when the file is not a readable audio file."""
    try:
        audio: Any = mutagen.File(path)
    except Exception as error:
        logger.warning("Cannot read %s: %s", path, error)
        return None
    if audio is None:
        return None
    raw, has_picture = _raw_tags(audio)
    info = _audio_info(audio, path.stat().st_size)
    return AudioFile(
        tags=build_track_tags(raw, has_picture=has_picture),
        info=info,
        chapters=_chapters(audio, info.duration_ms),
    )


# --- embedded pictures ----------------------------------------------------

_FRONT_COVER = 3  # ID3 / FLAC picture type


def extract_picture(path: Path) -> tuple[bytes, str] | None:
    """Embedded cover (front cover first) as (data, MIME type)."""
    try:
        audio: Any = mutagen.File(path)
    except Exception:
        return None
    if audio is None:
        return None
    tags = audio.tags
    candidates: list[tuple[int, bytes, str]] = []

    if isinstance(tags, ID3):
        candidates += [(f.type, f.data, f.mime) for f in tags.getall("APIC")]
    elif isinstance(tags, MP4Tags):
        for cover in tags.get("covr") or []:
            mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
            candidates.append((_FRONT_COVER, bytes(cover), mime))
    elif isinstance(tags, APEv2):
        for key, value in tags.items():
            if key.casefold().startswith("cover art") and value.kind == 1:
                # "<file name>\0<image data>"
                _, _, data = bytes(value).partition(b"\0")
                picture_type = _FRONT_COVER if "front" in key.casefold() else 0
                candidates.append((picture_type, data, _sniff_image_type(data)))
    elif isinstance(tags, ASFTags):
        pass  # WM/Picture is rare; not supported yet
    else:
        for picture in getattr(audio, "pictures", []):
            candidates.append((picture.type, picture.data, picture.mime))
        if tags is not None:
            for encoded in tags.get("metadata_block_picture", []):
                try:
                    picture = Picture(base64.b64decode(encoded))
                except Exception:
                    continue
                candidates.append((picture.type, picture.data, picture.mime))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0] != _FRONT_COVER)
    _, data, mime = candidates[0]
    return data, mime or _sniff_image_type(data)


def _sniff_image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"
