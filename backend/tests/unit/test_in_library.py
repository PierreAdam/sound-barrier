import pytest

from app.library_manager.in_library import clean_name


@pytest.mark.parametrize(
    ("name", "cleaned"),
    [
        ("Delain - Dark Waters (2023)", "delain dark waters"),
        ("Dethklok (FLAC)", "dethklok"),
        ("2023 - Dethalbum IV", "dethalbum iv"),
        ("Artist_-_Album.[320kbps].WEB", "artist album"),
        ("Album CD1 24bit 96kHz FLAC", "album"),
    ],
)
def test_clean_name(name: str, cleaned: str) -> None:
    assert clean_name(name) == cleaned


def test_albums_named_after_a_year() -> None:
    assert clean_name("Van Halen - 1984", keep_years=True) == "van halen 1984"
