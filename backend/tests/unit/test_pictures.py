import httpx

from app.external.pictures import Deezer, best_match


def test_exact_name_first() -> None:
    assert best_match("Dethklok", ["Dethklok Tribute", "dethklok"]) == 1
    assert best_match("Émilie Simon", ["Emilie Simon"]) == 0
    assert best_match("AC/DC", ["AC DC"]) == 0


def test_name_contained_as_whole_words() -> None:
    assert best_match("Dethklok", ["Metalocalypse: Dethklok", "Sethlo", "De Klok"]) == 0


def test_close_names_are_someone_else() -> None:
    assert best_match("Dethklok", ["Sethlo", "De Klok", "Dethkloks"]) is None
    assert best_match("", ["Anything"]) is None


# Several Deezer artists named "Dope" (in Deezer's order), as found in real life.
DOPE_SEARCH = [
    {"id": 1, "name": "Dope (FR)", "nb_fan": 1},
    {"id": 2, "name": "Dope", "nb_fan": 40},
    {"id": 3, "name": "Dope", "nb_fan": 6},
    {"id": 3087, "name": "DOPE", "nb_fan": 81601},
]
DOPE_ALBUMS = {
    2: ["Dope Beats Vol. 1"],
    3: ["Life"],  # shares one title with the real band
    3087: ["Felons and Revolutionaries", "Life", "American Apathy"],
}


def _deezer(requests: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        artist = int(request.url.path.split("/")[2])
        titles = DOPE_ALBUMS.get(artist, [])
        return httpx.Response(200, json={"data": [{"title": t} for t in titles]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def _choose(album_titles: list[str], requests: list[str] | None = None) -> int:
    async with _deezer(requests if requests is not None else []) as http:
        found = await Deezer()._choose(http, "Dope", DOPE_SEARCH, album_titles)  # pyright: ignore[reportPrivateUsage]
    assert found is not None
    return int(found["id"])


async def test_namesakes_the_one_with_the_library_albums() -> None:
    # "Felons and Revolutionaries (Remastered)" is the same album.
    assert await _choose(["Felons and Revolutionaries (Remastered)", "Life"]) == 3087


async def test_namesakes_a_less_famous_one_when_its_albums_match() -> None:
    assert await _choose(["Dope Beats Vol. 1"]) == 2


async def test_namesakes_the_most_followed_without_albums() -> None:
    requests: list[str] = []
    assert await _choose([], requests) == 3087
    assert requests == []  # nothing to compare: no album request
    assert await _choose(["Unknown Album"]) == 3087  # no album shared: the most followed
