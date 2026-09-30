"""The server player's queue (services/server_player.py): the rules of the web UI's own
player (frontend/src/player/engine.ts and queue.ts), so that a remote drives both alike.

Entries have a key, stable while they are queued (the same song may be queued twice):
remotes name entries by key, never by position. Tracks are kept as the web UI sent them
(checked: `track_from`), for the remotes to show; only their song id is used to play, and
their file comes from the library (a song the user may not play is never queued).
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

MAX_TRACKS = 5000
UNDO_LEVELS = 20
REPEAT_MODES = ("off", "all", "one")
MAX_TEXT = 500

_TEXT_FIELDS = ("id", "title", "artist", "album", "albumId", "artistId", "coverArt", "suffix")
_NUMBER_FIELDS = ("durationSeconds", "year", "size", "bitRate")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def track_from(value: object) -> dict[str, Any] | None:
    """A track from a remote (the web UI's `Track`): only the known fields, of the right
    types (as the web UI's `tracksFrom`). None: not a track."""
    if not isinstance(value, dict):
        return None
    raw = cast(dict[str, Any], value)
    track: dict[str, Any] = {}
    for name in _TEXT_FIELDS:
        text = raw.get(name)
        if isinstance(text, str):
            track[name] = text[:MAX_TEXT]
    for name in _NUMBER_FIELDS:
        number = _number(raw.get(name))
        if number is not None:
            track[name] = number
    if not track.get("id") or "title" not in track:
        return None
    if raw.get("longForm") is True:
        track["longForm"] = True
    if raw.get("spokenKind") in ("podcasts", "audiobooks"):
        track["spokenKind"] = raw["spokenKind"]
    chapters: list[dict[str, Any]] = []
    for item in cast(
        list[object], raw.get("chapters") if isinstance(raw.get("chapters"), list) else []
    ):
        chapter = cast(dict[str, Any], item) if isinstance(item, dict) else {}
        start = _number(chapter.get("start"))
        title = chapter.get("title")
        if start is not None and isinstance(title, str):
            chapters.append({"start": start, "title": title[:MAX_TEXT]})
    if chapters:
        track["chapters"] = sorted(chapters, key=lambda c: c["start"])
    return track


def tracks_from(value: object) -> list[dict[str, Any]]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return [t for t in (track_from(item) for item in items[:MAX_TRACKS]) if t is not None]


@dataclass(eq=False)
class Entry:
    key: int
    track: dict[str, Any]
    path: Path

    @property
    def long_form(self) -> bool:
        return self.track.get("longForm") is True

    @property
    def chapters(self) -> list[dict[str, Any]]:
        return self.track.get("chapters", [])

    @property
    def duration(self) -> float:
        return float(self.track.get("durationSeconds") or 0)


# This close before a chapter's start counts as in it (seeks may land a bit early).
CHAPTER_SLACK_SECONDS = 0.5


def chapter_index(chapters: Sequence[dict[str, Any]], position: float) -> int:
    """The chapter playing at `position`, -1 before the first / without chapters."""
    found = -1
    for i, chapter in enumerate(chapters):
        if chapter["start"] <= position + CHAPTER_SLACK_SECONDS:
            found = i
    return found


def next_index(index: int, length: int, repeat: str, automatic: bool) -> int | None:
    """What plays after `index` (None: stop); `automatic`: the track ended by itself."""
    if length == 0:
        return None
    if automatic and repeat == "one":
        return index
    if index + 1 < length:
        return index + 1
    return None if repeat == "off" else 0


def previous_index(index: int, length: int, repeat: str) -> int | None:
    if index > 0:
        return index - 1
    return length - 1 if repeat != "off" and length > 0 else None


class Queue:
    def __init__(self, shuffle_random: random.Random | None = None) -> None:
        self.original: list[Entry] = []  # the order it was queued in
        self.order: list[Entry] = []  # play order (shuffled or not)
        self.index = -1
        self.shuffle = False
        self.repeat = "off"
        self._history: list[tuple[list[Entry], list[Entry], int]] = []
        self._next_key = 0
        self._random = shuffle_random or random.Random()

    # --- reading ----------------------------------------------------------------------

    @property
    def current(self) -> Entry | None:
        return self.order[self.index] if 0 <= self.index < len(self.order) else None

    @property
    def spoken(self) -> bool:
        """An audiobook or a podcast plays: no shuffle, repeat or crossfade."""
        current = self.current
        return current is not None and current.long_form

    @property
    def repeat_mode(self) -> str:
        return "off" if self.spoken else self.repeat

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    def keys(self) -> list[int]:
        return [entry.key for entry in self.order]

    def position_of(self, key: object) -> int:
        return next((i for i, entry in enumerate(self.order) if entry.key == key), -1)

    # --- changes ----------------------------------------------------------------------

    def entries(self, items: Sequence[tuple[dict[str, Any], Path]]) -> list[Entry]:
        entries: list[Entry] = []
        for track, path in items:
            entries.append(Entry(self._next_key, track, path))
            self._next_key += 1
        return entries

    def replace(self, entries: list[Entry], start: int) -> None:
        """A new queue, at `entries[start]` (shuffled around it, unless it is spoken)."""
        if self.order:
            self._remember()
        self.original = entries[:MAX_TRACKS]
        first = self.original[start] if 0 <= start < len(self.original) else None
        if self.shuffle and first is not None and not first.long_form:
            self.order = self._shuffled(first)
            self.index = 0
        else:
            self.order = list(self.original)
            self.index = self.order.index(first) if first is not None else -1

    def add(self, entries: list[Entry]) -> bool:
        """At the end. True: the queue was empty (its first entry is now current)."""
        room = MAX_TRACKS - len(self.order)
        entries = entries[: max(room, 0)]
        self.original.extend(entries)
        self.order.extend(entries)
        if self.index == -1 and self.order:
            self.index = 0
            return True
        return False

    def play_next(self, entries: list[Entry]) -> bool:
        current = self.current
        if current is None:
            return self.add(entries)
        entries = entries[: max(MAX_TRACKS - len(self.order), 0)]
        self.order[self.index + 1 : self.index + 1] = entries
        at = self.original.index(current) + 1
        self.original[at:at] = entries
        return False

    def remove(self, keys: Sequence[object]) -> bool:
        """True: the current entry went (the following one, if any, is current now)."""
        doomed = {entry for entry in self.order if entry.key in set(keys)}
        if not doomed:
            return False
        self._remember()
        current = self.current
        removing_current = current is not None and current in doomed
        following = None
        if removing_current:
            following = next((e for e in self.order[self.index + 1 :] if e not in doomed), None)
        self.order = [e for e in self.order if e not in doomed]
        self.original = [e for e in self.original if e not in doomed]
        if not removing_current:
            self.index = self.order.index(current) if current is not None else -1
            return False
        self.index = self.order.index(following) if following is not None else -1
        return True

    def move(self, key: object, before: object) -> None:
        """Puts the entry `key` before the entry `before` (None: at the end)."""
        entry = next((e for e in self.order if e.key == key), None)
        if entry is None:
            return
        others = [e for e in self.order if e is not entry]
        if before is None:
            at = len(others)
        else:
            at = next((i for i, e in enumerate(others) if e.key == before), -1)
            if at < 0:
                return
        moved = [*others[:at], entry, *others[at:]]
        if moved == self.order:
            return
        self._remember()
        current = self.current
        self.order = moved
        if not self.shuffle:  # the manual order becomes the queue's
            self.original = list(self.order)
        self.index = self.order.index(current) if current is not None else -1

    def clear(self) -> None:
        if not self.order:
            return
        self._remember()
        self.original, self.order, self.index = [], [], -1

    def undo(self) -> bool:
        """Back to before the last change. True: the current entry is still queued."""
        if not self._history:
            return True
        current = self.current
        self.original, self.order, index = self._history.pop()
        if current is not None and current in self.order:
            self.index = self.order.index(current)
            return True
        self.index = index
        return False

    def toggle_shuffle(self) -> None:
        if self.spoken:
            return
        current = self.current
        self.shuffle = not self.shuffle
        if self.shuffle:
            self.order = self._shuffled(current)
            self.index = 0 if current is not None else -1
        else:
            self.order = list(self.original)
            self.index = self.order.index(current) if current is not None else -1

    def cycle_repeat(self) -> None:
        if not self.spoken:
            self.repeat = REPEAT_MODES[(REPEAT_MODES.index(self.repeat) + 1) % len(REPEAT_MODES)]

    def _shuffled(self, first: Entry | None) -> list[Entry]:
        rest = [e for e in self.original if e is not first]
        self._random.shuffle(rest)
        return rest if first is None else [first, *rest]

    def _remember(self) -> None:
        self._history.append((list(self.original), list(self.order), self.index))
        del self._history[:-UNDO_LEVELS]
