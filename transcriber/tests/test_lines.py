from sb_transcriber.lines import MAX_CHARS, Segment, Word, to_lines


def _words(text: str, start: float = 0.0, step: float = 0.3) -> list[Word]:
    """Like Whisper: a leading space before each word ("|" glues two pieces: "C'|était")."""
    pieces = [(" " + p if i == 0 else p) for w in text.split() for i, p in enumerate(w.split("|"))]
    return [Word(start + i * step, start + i * step + 0.25, p) for i, p in enumerate(pieces)]


def test_sentences_become_lines() -> None:
    words = _words(
        "It was a dark and stormy night. The rain fell in torrents, except at intervals."
    )
    lines = to_lines([Segment(0, 30, "", words)])
    assert [line["text"] for line in lines] == [
        "It was a dark and stormy night.",
        "The rain fell in torrents, except at intervals.",
    ]
    assert lines[0]["startMs"] == 0
    assert lines[1]["startMs"] == round(7 * 0.3 * 1000)
    assert lines[0]["words"][1] == {"startMs": 300, "text": "was "}
    assert lines[0]["words"][-1]["text"] == "night."


def test_short_sentences_stay_together() -> None:
    lines = to_lines([Segment(0, 5, "", _words("Yes. No. Maybe so, said the man at last."))])
    assert [line["text"] for line in lines] == ["Yes. No. Maybe so, said the man at last."]


def test_a_pause_starts_a_line() -> None:
    first = _words("Chapter one", 0.0)
    second = _words("In which we meet the hero", 5.0)
    lines = to_lines([Segment(0, 3, "", first), Segment(5, 9, "", second)])
    assert [line["text"] for line in lines] == ["Chapter one", "In which we meet the hero"]


def test_long_lines_are_cut_at_a_comma() -> None:
    text = (
        "and so they walked for days along the river that ran through the valley, "
        "never stopping to rest nor to eat nor to speak"
    )
    lines = to_lines([Segment(0, 30, "", _words(text, step=0.1))])
    assert all(len(line["text"]) <= MAX_CHARS for line in lines)
    assert lines[0]["text"].endswith("valley,")
    assert " ".join(line["text"] for line in lines) == text


def test_segments_without_word_timing() -> None:
    lines = to_lines([Segment(1.5, 4.0, "  Hello   there. "), Segment(4.0, 5.0, "  ")])
    assert lines == [
        {
            "startMs": 1500,
            "endMs": 4000,
            "text": "Hello there.",
            "words": [{"startMs": 1500, "text": "Hello there."}],
        }
    ]


def test_elisions_stay_glued() -> None:
    lines = to_lines([Segment(0, 5, "", _words("C'|était un jour froid dans l'|avril."))])
    assert [line["text"] for line in lines] == ["C'était un jour froid dans l'avril."]
    assert [w["text"] for w in lines[0]["words"]][:3] == ["C'", "était ", "un "]


def test_long_lines_are_never_cut_inside_a_word() -> None:
    text = "a" + " bb" * 40 + " l'|avril"
    lines = to_lines([Segment(0, 30, "", _words(text, step=0.05))])
    assert all(not line["text"].startswith("avril") for line in lines)
    assert " ".join(line["text"] for line in lines).replace("l' avril", "l'avril") == text.replace(
        "|", ""
    )
