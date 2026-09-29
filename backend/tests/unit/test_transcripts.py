from app.services import lyrics, transcripts


def test_word_spacing() -> None:
    """Whisper's leading spaces, or trailing ones; none: glued (French elisions)."""
    whisper = [
        {"startMs": 0, "text": " C'"},
        {"startMs": 1, "text": "était"},
        {"startMs": 2, "text": " l'"},
        {"startMs": 3, "text": "hiver."},
    ]
    trailing = [
        {"startMs": 0, "text": "C'"},
        {"startMs": 1, "text": "était "},
        {"startMs": 2, "text": "l'"},
        {"startMs": 3, "text": "hiver. "},
    ]
    for given in (whisper, trailing):
        assert [w["text"] for w in transcripts._spaced_words(given)] == [
            "C'",
            "était ",
            "l'",
            "hiver.",
        ]  # pyright: ignore[reportPrivateUsage]


def test_lrc_of_a_long_file() -> None:
    """An audiobook file can last hours: minutes pass 99, and 999."""
    lines = [
        {"startMs": 0, "text": "Start."},
        {"startMs": 6_012_340, "text": "After 100 minutes."},
        {"startMs": 60_000_000, "text": "After 1000 minutes."},
    ]
    text = transcripts.to_lrc("Chapter", "Author", "whisper large-v3", lines)
    assert text.splitlines() == [
        transcripts.LRC_MARKER,
        "[ti:Chapter]",
        "[ar:Author]",
        "[by:whisper large-v3]",
        "[00:00.00]Start.",
        "[100:12.34]After 100 minutes.",
        "[1000:00.00]After 1000 minutes.",
    ]
    synced, parsed = lyrics.parse(text)
    assert synced
    assert [(line.start_ms, line.text) for line in parsed] == [
        (0, "Start."),
        (6_012_340, "After 100 minutes."),
        (60_000_000, "After 1000 minutes."),
    ]
