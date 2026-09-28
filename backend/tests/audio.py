"""Builds tagged audio files for tests from the silent fixtures in tests/fixtures/audio."""
# mutagen has no type information.
# pyright: basic

import base64
import shutil
from pathlib import Path
from typing import Any

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TXXX, UFID, Frames
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

FIXTURES = Path(__file__).parent / "fixtures" / "audio"
COVER_JPG = FIXTURES / "cover.jpg"
FORMATS = ("mp3", "flac", "m4a", "ogg", "opus")

# Canonical key -> ID3 frame / MP4 atom. Vorbis uses the canonical key in upper case.
_ID3 = {
    "title": "TIT2",
    "artist": "TPE1",
    "albumartist": "TPE2",
    "album": "TALB",
    "tracknumber": "TRCK",
    "discnumber": "TPOS",
    "date": "TDRC",
    "originaldate": "TDOR",
    "genre": "TCON",
    "composer": "TCOM",
    "compilation": "TCMP",
    "albumsort": "TSOA",
    "artistsort": "TSOP",
    "discsubtitle": "TSST",
}
_ID3_TXXX = {
    "artists": "ARTISTS",
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "releasetype": "MusicBrainz Album Type",
    "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
}
_MP4 = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "albumartist": "aART",
    "album": "\xa9alb",
    "date": "\xa9day",
    "genre": "\xa9gen",
    "composer": "\xa9wrt",
}
_MP4_FREEFORM = {
    "artists": "ARTISTS",
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "releasetype": "MusicBrainz Album Type",
}


def album_tracks(root: Path, artist: str, album: str, count: int, **tags: Any) -> list[Path]:
    """`count` MP3 tracks in `root/artist/album/`, tagged with the album and artist."""
    return [
        make_track(
            root / artist / album / f"{n:02d} - Track {n}",
            title=f"Track {n}",
            artist=artist,
            albumartist=artist,
            album=album,
            tracknumber=f"{n}/{count}",
            **tags,
        )
        for n in range(1, count + 1)
    ]


def make_track(
    dest: Path, *, fmt: str = "mp3", picture: bool = False, **tags: str | list[str]
) -> Path:
    """Copies a silent fixture to `dest` (suffix added) and writes the given tags.

    Tag names are canonical keys (`title`, `albumartist`, `musicbrainz_albumid`...).
    List values are written as multi-valued tags.
    """
    path = dest.with_suffix(f".{fmt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / f"silence.{fmt}", path)
    values = {k: v if isinstance(v, list) else [v] for k, v in tags.items()}
    image = COVER_JPG.read_bytes() if picture else None
    if fmt == "mp3":
        _write_id3(path, values, image)
    elif fmt == "m4a":
        _write_mp4(path, values, image)
    else:
        _write_vorbis(path, fmt, values, image)
    return path


def _write_id3(path: Path, values: dict[str, list[str]], image: bytes | None) -> None:
    id3 = ID3()
    for key, vals in values.items():
        if key in _ID3:
            id3.add(Frames[_ID3[key]](encoding=3, text=vals))
        elif key in _ID3_TXXX:
            id3.add(TXXX(encoding=3, desc=_ID3_TXXX[key], text=vals))
        elif key == "musicbrainz_trackid":
            id3.add(UFID(owner="http://musicbrainz.org", data=vals[0].encode()))
        else:
            raise ValueError(f"unsupported test tag for mp3: {key}")
    if image:
        id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=image))
    id3.save(path)


def _write_mp4(path: Path, values: dict[str, list[str]], image: bytes | None) -> None:
    audio: Any = MP4(path)
    for key, vals in values.items():
        if key in _MP4:
            audio[_MP4[key]] = vals
        elif key in ("tracknumber", "discnumber"):
            number, _, total = vals[0].partition("/")
            atom = "trkn" if key == "tracknumber" else "disk"
            audio[atom] = [(int(number), int(total or 0))]
        elif key == "compilation":
            audio["cpil"] = vals[0] == "1"
        elif key in _MP4_FREEFORM:
            name = f"----:com.apple.iTunes:{_MP4_FREEFORM[key]}"
            audio[name] = [MP4FreeForm(v.encode()) for v in vals]
        else:
            raise ValueError(f"unsupported test tag for m4a: {key}")
    if image:
        audio["covr"] = [MP4Cover(image, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _write_vorbis(path: Path, fmt: str, values: dict[str, list[str]], image: bytes | None) -> None:
    audio: Any = {"flac": FLAC, "ogg": OggVorbis, "opus": OggOpus}[fmt](path)
    for key, vals in values.items():
        audio[key.upper()] = vals
    if image:
        picture = Picture()
        picture.type, picture.mime, picture.data = 3, "image/jpeg", image
        if fmt == "flac":
            audio.add_picture(picture)
        else:
            audio["METADATA_BLOCK_PICTURE"] = [base64.b64encode(picture.write()).decode()]
    audio.save()
