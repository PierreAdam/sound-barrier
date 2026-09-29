from app.services.lyrics import Line, parse


def test_lrc_lines_are_timed_and_sorted() -> None:
    synced, lines = parse(
        "[ar:Delain]\n[ti:Moth to a Flame]\n[00:12.5]First\n[00:05.00][01:02.123]Chorus\n\n"
    )
    assert synced is True
    assert lines == [Line(5000, "Chorus"), Line(12500, "First"), Line(62123, "Chorus")]


def test_offset_shifts_the_lines() -> None:
    _, lines = parse("[offset:+500]\n[00:10.00]Line")
    assert lines == [Line(9500, "Line")]


def test_plain_text() -> None:
    synced, lines = parse("\n\nVerse one\nVerse two\n\nChorus\n\n")
    assert synced is False
    assert [line.text for line in lines] == ["Verse one", "Verse two", "", "Chorus"]


def test_enhanced_lrc_word_timing() -> None:
    synced, lines = parse(
        "[00:10.00]<00:10.00>Word <00:10.50>by <00:11.00>word\n[00:12.00]Plain line"
    )
    assert synced is True
    assert lines[0].text == "Word by word"
    assert [(w.start_ms, w.text) for w in lines[0].words or []] == [
        (10000, "Word "),
        (10500, "by "),
        (11000, "word"),
    ]
    assert lines[1].words is None


def test_repeated_lines_move_their_words() -> None:
    _, lines = parse("[00:10.00][01:00.00]<00:10.00>La <00:10.40>la")
    assert [w.start_ms for w in lines[1].words or []] == [60000, 60400]
