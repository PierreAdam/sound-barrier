"""Whisper's segments -> subtitle-sized lines (what the server stores and players show).

Whisper's segments are up to ~30 s of speech, too long to read along. The words (with
their timing) are regrouped into lines: a line ends after a sentence (once it is long
enough), at a pause, or when it gets too long (at a comma if there is one).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

MIN_CHARS = 25  # a sentence shorter than that goes on with the next one
MAX_CHARS = 84
MAX_SECONDS = 8.0
PAUSE_SECONDS = 1.2  # a silence this long starts a new line
SENTENCE_END = (".", "?", "!", "…", '."', '?"', '!"', ".»", "?»", "!»")
CLAUSE_END = (",", ";", ":", "—")


@dataclass
class Word:
    start: float  # seconds
    end: float
    # As Whisper gives it: a leading space starts a new word, none continues the previous
    # one (French "C'" + "était", "l'" + "hiver").
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list[Word])


@dataclass
class _Line:
    words: list[Word] = field(default_factory=list[Word])

    @property
    def text(self) -> str:
        return " ".join("".join(w.text for w in self.words).split())

    def seconds(self) -> float:
        return self.words[-1].end - self.words[0].start if self.words else 0.0


def _ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def _spaced(words: list[Word]) -> list[dict[str, Any]]:
    """The words as the server takes them: a trailing space when the next word is a new
    one ("C'" then "était": no space between them)."""
    found: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        after = index + 1 < len(words) and words[index + 1].text[:1].isspace()
        found.append(
            {"startMs": _ms(word.start), "text": word.text.strip() + (" " if after else "")}
        )
    return found


def _out(line: _Line) -> dict[str, Any]:
    return {
        "startMs": _ms(line.words[0].start),
        "endMs": _ms(line.words[-1].end),
        "text": line.text,
        "words": _spaced(line.words),
    }


def _split_long(line: _Line) -> tuple[_Line, _Line]:
    """Cuts a too long line at its last comma in the second half, else before its last
    word (never inside a word: "C'" + "était" stay together)."""
    words = line.words
    for index in range(len(words) - 2, 0, -1):
        if words[index].text.strip().endswith(CLAUSE_END) and index >= len(words) // 2:
            return _Line(words[: index + 1]), _Line(words[index + 1 :])
    for index in range(len(words) - 1, 0, -1):
        if words[index].text[:1].isspace():
            return _Line(words[:index]), _Line(words[index:])
    return _Line(words[:-1]), _Line(words[-1:])


def to_lines(segments: Iterable[Segment]) -> list[dict[str, Any]]:
    """The lines, as the server takes them (`startMs`, `endMs`, `text`, `words`)."""
    lines: list[dict[str, Any]] = []
    current = _Line()

    def flush() -> None:
        nonlocal current
        if current.words:
            lines.append(_out(current))
        current = _Line()

    for segment in segments:
        words = [w for w in segment.words if w.text.strip()]
        if not words:  # no word timing: the segment is one line
            text = " ".join(segment.text.split())
            if text:
                flush()
                current = _Line([Word(segment.start, segment.end, " " + text)])
                flush()
            continue
        for word in words:
            new_word = word.text[:1].isspace() or not current.words
            if new_word and current.words and word.start - current.words[-1].end >= PAUSE_SECONDS:
                flush()
            current.words.append(word)
            if len(current.text) > MAX_CHARS or current.seconds() > MAX_SECONDS:
                if len(current.words) == 1:
                    flush()
                    continue
                done, current = _split_long(current)
                lines.append(_out(done))
            elif word.text.strip().endswith(SENTENCE_END) and len(current.text) >= MIN_CHARS:
                flush()
    flush()
    return lines
