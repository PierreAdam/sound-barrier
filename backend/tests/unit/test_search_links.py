import io

import pytest
from PIL import Image

from app.plugins.base import PluginSettingsError, WantedAlbum
from app.plugins.search_links import SearchLinks, icons

ALBUM = WantedAlbum(artist="Visions of Atlantis", title="Pirates & Co", year="2022")


def _site(**values: str) -> dict[str, str]:
    return {"name": "Store", "url": "https://store.example/search?q={query}", **values}


def test_get_links_encode_the_values() -> None:
    plugin = SearchLinks()
    settings = plugin.validate(
        {"sites": [_site(url="https://store.example/{artist}/search?q={album}&y={year}")]}
    )
    [link] = plugin.links(ALBUM, settings)
    assert link.url == "https://store.example/Visions+of+Atlantis/search?q=Pirates+%26+Co&y=2022"
    assert (link.method, link.form) == ("GET", [])


def test_post_links_are_form_fields() -> None:
    plugin = SearchLinks()
    body = "SearchForm%5Bn%5D={query}&go-search=Search"
    settings = plugin.validate(
        {"sites": [_site(method="POST", url="https://s.example/", body=body)]}
    )
    [link] = plugin.links(ALBUM, settings)
    assert link.method == "POST"
    assert link.form == [
        ("SearchForm[n]", "Visions of Atlantis Pirates & Co"),
        ("go-search", "Search"),
    ]


def test_disabled_sites_and_ids() -> None:
    plugin = SearchLinks()
    settings = plugin.validate(
        {"sites": [_site(id="a"), _site(id="a", enabled=False), _site(id="Bad Id!")]}  # type: ignore[arg-type]
    )
    ids = [site["id"] for site in settings["sites"]]
    assert ids[0] == "a" and len(set(ids)) == 3  # duplicates and bad ids get a new one
    assert len(plugin.links(ALBUM, settings)) == 2
    assert len(plugin.links(ALBUM, settings, include_disabled=True)) == 3


@pytest.mark.parametrize(
    ("site", "message"),
    [
        (_site(url="https://store.example/search?q={title}"), "unknown placeholder {title}"),
        (_site(url="https://store.example/search"), "at least one placeholder"),
        (_site(url="ftp://store.example/{query}"), "http"),
        (_site(method="POST", body=""), "form fields"),
        (_site(name=""), "name"),
    ],
)
def test_invalid_sites(site: dict[str, str], message: str) -> None:
    with pytest.raises(PluginSettingsError, match=message):
        SearchLinks().validate({"sites": [site]})


def test_default_sites() -> None:
    plugin = SearchLinks()
    settings = plugin.validate(plugin.default_settings())
    assert [s["name"] for s in settings["sites"]] == ["DuckDuckGo", "Amazon.fr", "Fnac"]
    fnac = plugin.links(ALBUM, settings)[2]
    assert fnac.url.startswith(
        "https://www.fnac.com/SearchResult/ResultList.aspx?Search=Visions+of+Atlantis+Pirates"
    )


def test_icon_links_biggest_first_without_svg() -> None:
    parser = icons._IconLinks()  # pyright: ignore[reportPrivateUsage]
    parser.feed(
        '<link rel="icon" href="/small.png" sizes="16x16">'
        '<link rel="apple-touch-icon" href="/touch.png">'
        '<link rel="icon" href="/logo.svg">'
        '<link rel="mask-icon" href="/mask.png">'
        '<link rel="shortcut icon" href="/big.png" sizes="96x96">'
    )
    assert [href for _, href in sorted(parser.found, key=lambda f: -f[0])] == [
        "/touch.png",
        "/big.png",
        "/small.png",
    ]


def test_icons_become_small_pngs() -> None:
    source = io.BytesIO()
    Image.new("RGB", (128, 64), (200, 20, 20)).save(source, format="ICO", sizes=[(128, 64)])
    png = icons._png(source.getvalue())  # pyright: ignore[reportPrivateUsage]
    with Image.open(io.BytesIO(png)) as image:
        assert (image.format, image.size) == ("PNG", (icons.ICON_SIZE, icons.ICON_SIZE))
    with pytest.raises(icons.IconError):
        icons._png(b"<svg xmlns='http://www.w3.org/2000/svg'/>")  # pyright: ignore[reportPrivateUsage]
