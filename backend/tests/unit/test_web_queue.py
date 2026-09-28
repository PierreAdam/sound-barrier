import uuid

from app.services.web_queue import keep_available

A, B, C, D = (uuid.uuid4() for _ in range(4))


def test_nothing_missing() -> None:
    kept = keep_available([A, B, C], [2, 0, 1], 1, 5000, {A, B, C})
    assert (kept.song_ids, kept.original_order, kept.current_index, kept.position_ms) == (
        [A, B, C],
        [2, 0, 1],
        1,
        5000,
    )


def test_missing_song_before_the_current_one() -> None:
    kept = keep_available([A, B, C, D], [3, 0, 1, 2], 2, 5000, {B, C, D})
    assert kept.song_ids == [B, C, D]
    assert kept.original_order == [2, 0, 1]
    assert (kept.current_index, kept.position_ms) == (1, 5000)  # still C, same position


def test_current_song_missing() -> None:
    kept = keep_available([A, B, C], None, 1, 5000, {A, C})
    assert (kept.song_ids, kept.current_index, kept.position_ms) == ([A, C], 1, 0)  # C
    kept = keep_available([A, B, C], None, 2, 5000, {A, B})
    assert (kept.current_index, kept.position_ms) == (1, 0)  # last one gone: B
    kept = keep_available([A, B], None, 0, 5000, set())
    assert (kept.song_ids, kept.current_index) == ([], -1)
