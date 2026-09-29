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
