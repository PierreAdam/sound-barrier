from app.external.pictures import best_match


def test_exact_name_first() -> None:
    assert best_match("Dethklok", ["Dethklok Tribute", "dethklok"]) == 1
    assert best_match("Émilie Simon", ["Emilie Simon"]) == 0
    assert best_match("AC/DC", ["AC DC"]) == 0


def test_name_contained_as_whole_words() -> None:
    assert best_match("Dethklok", ["Metalocalypse: Dethklok", "Sethlo", "De Klok"]) == 0


def test_close_names_are_someone_else() -> None:
    assert best_match("Dethklok", ["Sethlo", "De Klok", "Dethkloks"]) is None
    assert best_match("", ["Anything"]) is None
