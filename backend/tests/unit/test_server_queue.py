"""The server player's queue: the web UI player's rules (frontend/src/player/engine.ts)."""

import random
from pathlib import Path
from typing import Any

from app.services.server_queue import (
    Queue,
    chapter_index,
    next_index,
    previous_index,
    track_from,
    tracks_from,
)


def _queue(ids: str = "abcd", *, shuffle: bool = False) -> Queue:
    queue = Queue(random.Random(1))
    queue.shuffle = shuffle
    entries = queue.entries([({"id": i, "title": i.upper()}, Path(f"{i}.mp3")) for i in ids])
    queue.replace(entries, 0)
    return queue


def _ids(queue: Queue) -> str:
    return "".join(entry.track["id"] for entry in queue.order)


def _key(queue: Queue, song: str) -> int:
    return next(e.key for e in queue.order if e.track["id"] == song)


def test_tracks_keep_only_known_fields_of_the_right_types() -> None:
    raw: dict[str, Any] = {
        "id": "s1",
        "title": "Song",
        "artist": 42,  # not text: left out
        "durationSeconds": 180,
        "longForm": "yes",  # only true counts
        "chapters": [{"start": 60, "title": "Two"}, {"start": 0, "title": "One"}, {"x": 1}],
        "evil": "<script>",
    }
    assert track_from(raw) == {
        "id": "s1",
        "title": "Song",
        "durationSeconds": 180.0,
        "chapters": [{"start": 0.0, "title": "One"}, {"start": 60.0, "title": "Two"}],
    }
    assert track_from({"title": "no id"}) is None
    assert tracks_from([raw, "junk", None]) == [track_from(raw)]


def test_tracks_keep_their_place_in_the_book() -> None:
    place = {"start": 3600, "duration": 7200.5, "chapter": 3, "chapters": 10}
    track = track_from({"id": "s1", "title": "Part 2", "book": place})
    assert track is not None and track["book"] == {k: float(v) for k, v in place.items()}
    # Incomplete or of the wrong types: left out.
    for book in ({"start": 0, "duration": 1, "chapter": 0}, {**place, "chapters": "10"}, "x"):
        assert "book" not in (track_from({"id": "s1", "title": "T", "book": book}) or {})


def test_add_play_next_and_remove_by_key() -> None:
    queue = Queue()
    assert queue.add(queue.entries([({"id": "a", "title": "A"}, Path("a"))])) is True
    assert queue.index == 0  # the first one queued is current (not playing)
    queue.add(queue.entries([({"id": "c", "title": "C"}, Path("c"))]))
    queue.play_next(queue.entries([({"id": "b", "title": "B"}, Path("b"))]))
    assert _ids(queue) == "abc"

    # Removing the current entry: the following one is current.
    assert queue.remove([_key(queue, "a")]) is True
    assert (_ids(queue), queue.current and queue.current.track["id"]) == ("bc", "b")
    # Unknown keys: nothing happens (a remote's view was outdated).
    assert queue.remove([999]) is False
    assert _ids(queue) == "bc"


def test_move_by_key() -> None:
    queue = _queue()
    queue.move(_key(queue, "d"), _key(queue, "b"))  # d before b
    assert _ids(queue) == "adbc"
    queue.move(_key(queue, "a"), None)  # the current one, to the end
    assert _ids(queue) == "dbca"
    assert queue.index == 3  # still the current one
    queue.move(_key(queue, "b"), 999)  # before an entry gone: nothing
    assert _ids(queue) == "dbca"


def test_undo_restores_the_queue_and_keeps_playing_what_plays() -> None:
    queue = _queue()
    queue.index = 1  # "b" plays
    queue.remove([_key(queue, "c")])
    queue.move(_key(queue, "d"), _key(queue, "a"))
    assert _ids(queue) == "dab"
    assert queue.undo() is True
    assert _ids(queue) == "abd"
    assert queue.undo() is True
    assert (_ids(queue), queue.index) == ("abcd", 1)

    queue.clear()
    assert queue.current is None
    assert queue.undo() is False  # the current entry is back, but was not playing
    assert _ids(queue) == "abcd"


def test_shuffle_keeps_the_current_one_first_and_restores_the_order() -> None:
    queue = _queue("abcdefgh")
    queue.index = 2
    queue.toggle_shuffle()
    assert queue.order[0].track["id"] == "c"
    assert queue.index == 0
    assert sorted(_ids(queue)) == list("abcdefgh")
    queue.toggle_shuffle()
    assert (_ids(queue), queue.index) == ("abcdefgh", 2)

    # A new queue while shuffling: shuffled around the chosen track.
    shuffled = _queue("abcdefgh", shuffle=True)
    assert shuffled.order[0].track["id"] == "a"
    assert shuffled.index == 0


def test_spoken_tracks_have_no_shuffle_or_repeat() -> None:
    queue = Queue()
    book = [({"id": "b1", "title": "Chapter 1", "longForm": True}, Path("b1"))]
    queue.replace(queue.entries(book), 0)
    queue.repeat = "all"
    assert queue.repeat_mode == "off"
    queue.toggle_shuffle()
    queue.cycle_repeat()
    assert (queue.shuffle, queue.repeat) == (False, "all")


def test_navigation_rules() -> None:
    assert next_index(1, 3, "off", False) == 2
    assert next_index(2, 3, "off", True) is None
    assert next_index(2, 3, "all", True) == 0
    assert next_index(1, 3, "one", True) == 1  # the track ended by itself: again
    assert next_index(1, 3, "one", False) == 2  # "next" clicked: the next one
    assert previous_index(0, 3, "off") is None
    assert previous_index(0, 3, "all") == 2
    chapters = [{"start": 0.0, "title": "1"}, {"start": 60.0, "title": "2"}]
    assert chapter_index(chapters, 59.8) == 1  # a seek landing just before counts
    assert chapter_index(chapters, 30) == 0
    assert chapter_index([], 30) == -1
