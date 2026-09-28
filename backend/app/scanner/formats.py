"""Supported file types."""

# Audio suffix -> MIME type returned as Subsonic `contentType`.
AUDIO_CONTENT_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
    "m4b": "audio/mp4",
    "aac": "audio/aac",
    "wma": "audio/x-ms-wma",
    "wav": "audio/wav",
    "aif": "audio/aiff",
    "aiff": "audio/aiff",
    "ape": "audio/x-ape",
    "wv": "audio/x-wavpack",
    "mpc": "audio/x-musepack",
    "dsf": "audio/x-dsf",
}

IMAGE_CONTENT_TYPES: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

# Folder images used as album cover, by priority (file name without extension).
COVER_FILE_NAMES = ("cover", "folder", "front", "album", "albumart")


def suffix_of(name: str) -> str:
    _, dot, suffix = name.rpartition(".")
    return suffix.lower() if dot else ""
