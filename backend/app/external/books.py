"""Looking up audiobooks and podcasts for the import review: Audible's catalog
(unofficial, no key), MusicBrainz (audiobook releases: their track lists give chapter
titles), Open Library (no key) and iTunes Search (podcasts, no key). Only titles and
author names are sent."""

import html
import re
from dataclasses import asdict, dataclass, field
from typing import Any, cast

import httpx

from app.external import ExternalServiceError, musicbrainz

AUDIBLE_REGIONS = ("com", "co.uk", "fr", "de", "ca", "com.au", "it", "es", "in", "co.jp")
MAX_RESULTS = 8

_TAGS = re.compile(r"<[^>]+>")


@dataclass
class BookCandidate:
    """A book / show found online, as the review shows it."""

    # "audible:<asin>", "musicbrainz:<release>", "openlibrary:<work>", "itunes:<id>"
    id: str
    source: str  # Audible, MusicBrainz, Open Library, iTunes
    title: str
    authors: list[str] = field(default_factory=list[str])
    narrators: list[str] = field(default_factory=list[str])
    series: str | None = None
    series_number: str | None = None
    year: int | None = None
    duration_ms: int | None = None
    description: str | None = None
    genre: str | None = None
    cover_url: str | None = None
    url: str | None = None  # its page on the service
    # MusicBrainz: the edition's tracks, when fetched (its track count matches the files).
    track_count: int | None = None
    tracks: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])  # title, duration_ms
    release_group_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


async def _json(http: httpx.AsyncClient, name: str, url: str, params: dict[str, str]) -> Any:
    try:
        response = await http.get(url, params=params)
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"{name} is not reachable: {error}") from error
    if response.status_code != 200:
        raise ExternalServiceError(f"{name} error (HTTP {response.status_code})")
    try:
        return response.json()
    except ValueError as error:
        raise ExternalServiceError(f"Invalid answer from {name}") from error


def _dicts(value: Any) -> list[dict[str, Any]]:
    """The objects of a JSON list (anything else ignored)."""
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], v) for v in cast(list[Any], value) if isinstance(v, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _text(value: Any) -> str | None:
    """Plain text of an HTML summary."""
    if not isinstance(value, str) or not value.strip():
        return None
    return html.unescape(_TAGS.sub(" ", value)).replace("  ", " ").strip() or None


def without_series(title: str, series: str | None) -> str:
    """ "Carl's Doomsday Scenario: Dungeon Crawler Carl, Book 2" -> "Carl's Doomsday
    Scenario" when the series is known (it has its own field)."""
    if not series:
        return title
    numbered = r"(book|volume|vol\.|tome|band|livre)\s*[\d.]+"
    patterns = [
        rf"\s*[:,\-(]\s*{re.escape(series)}\s*,?\s*{numbered}\)?\s*$",
        rf"\s*[,:(]\s*{numbered}\)?\s*$",
    ]
    for pattern in patterns:
        stripped = re.sub(pattern, "", title, flags=re.I).strip()
        if stripped and stripped != title:
            return stripped
    return title


def _year(value: Any) -> int | None:
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _names(values: Any) -> list[str]:
    return [name for v in _dicts(values) if (name := _str(v.get("name")))]


async def audible(
    http: httpx.AsyncClient, title: str, author: str | None, region: str = "com"
) -> list[BookCandidate]:
    if region not in AUDIBLE_REGIONS:
        region = "com"
    params = {
        "title": title,
        "num_results": str(MAX_RESULTS),
        "products_sort_by": "Relevance",
        "response_groups": "contributors,product_desc,product_attrs,media,series",
    }
    if author:
        params["author"] = author
    data = _dict(
        await _json(http, "Audible", f"https://api.audible.{region}/1.0/catalog/products", params)
    )
    found: list[BookCandidate] = []
    for product in _dicts(data.get("products")):
        asin, name = _str(product.get("asin")), _str(product.get("title"))
        if not asin or not name:
            continue
        series = next(iter(_dicts(product.get("series"))), dict[str, Any]())
        series_title = _str(series.get("title"))
        images = {
            k: v for k, v in _dict(product.get("product_images")).items() if isinstance(v, str)
        }
        runtime = product.get("runtime_length_min")
        found.append(
            BookCandidate(
                id=f"audible:{asin}",
                source="Audible",
                title=without_series(name, series_title),
                authors=_names(product.get("authors")),
                narrators=_names(product.get("narrators")),
                series=series_title,
                series_number=_str(series.get("sequence")),
                year=_year(product.get("release_date")),
                duration_ms=int(runtime) * 60_000 if isinstance(runtime, int) and runtime else None,
                description=_text(product.get("publisher_summary"))
                or _text(product.get("merchandising_summary"))
                or _str(product.get("subtitle")),
                cover_url=images.get("500") or next(iter(images.values()), None),
                url=f"https://www.audible.{region}/pd/{asin}",
            )
        )
    return found


async def open_library(
    http: httpx.AsyncClient, title: str, author: str | None
) -> list[BookCandidate]:
    params = {
        "title": title,
        "limit": str(MAX_RESULTS),
        "fields": "key,title,author_name,first_publish_year,cover_i",
    }
    if author:
        params["author"] = author
    data = _dict(await _json(http, "Open Library", "https://openlibrary.org/search.json", params))
    found: list[BookCandidate] = []
    for doc in _dicts(data.get("docs")):
        key, name = _str(doc.get("key")), _str(doc.get("title"))
        if not key or not name:
            continue
        cover = doc.get("cover_i")
        authors = doc.get("author_name")
        found.append(
            BookCandidate(
                id=f"openlibrary:{key}",
                source="Open Library",
                title=name,
                authors=[a for a in cast(list[Any], authors) if isinstance(a, str)][:3]
                if isinstance(authors, list)
                else [],
                year=_year(doc.get("first_publish_year")),
                cover_url=f"https://covers.openlibrary.org/b/id/{cover}-L.jpg" if cover else None,
                url=f"https://openlibrary.org{key}",
            )
        )
    return found


async def itunes_podcasts(http: httpx.AsyncClient, name: str) -> list[BookCandidate]:
    params = {"media": "podcast", "entity": "podcast", "term": name, "limit": str(MAX_RESULTS)}
    data = _dict(await _json(http, "iTunes", "https://itunes.apple.com/search", params))
    found: list[BookCandidate] = []
    for result in _dicts(data.get("results")):
        collection, title = result.get("collectionId"), _str(result.get("collectionName"))
        if not collection or not title:
            continue
        artist = _str(result.get("artistName"))
        found.append(
            BookCandidate(
                id=f"itunes:{collection}",
                source="iTunes",
                title=title,
                authors=[artist] if artist else [],
                year=_year(result.get("releaseDate")),
                genre=_str(result.get("primaryGenreName")),
                cover_url=_str(result.get("artworkUrl600")) or _str(result.get("artworkUrl100")),
                url=_str(result.get("collectionViewUrl")),
            )
        )
    return found


# Where an audiobook's artist credit turns from the author(s) to the narrator(s):
# "J.K. Rowling read by Stephen Fry".
_READ_BY = re.compile(
    r"\b(read by|narrated by|performed by|lu par|raconté par|gelesen von|letto da|leído por)\b",
    re.I,
)
MUSICBRAINZ_DETAILS = 2  # editions whose tracks are fetched (one request per second)


def _credits(release: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(authors, narrators) of an audiobook release's artist credit."""
    authors: list[str] = []
    narrators: list[str] = []
    target = authors
    for credit in _dicts(release.get("artist-credit")):
        name = _str(credit.get("name"))
        if name:
            target.append(name)
        if _READ_BY.search(str(credit.get("joinphrase") or "")):
            target = narrators
    return authors, narrators


def _lucene(value: str) -> str:
    """A phrase for MusicBrainz's search syntax."""
    return '"' + re.sub(r'["\\]', " ", value).strip() + '"'


async def musicbrainz_audiobooks(
    http: httpx.AsyncClient, title: str, author: str | None, files: int
) -> list[BookCandidate]:
    """Audiobook releases (secondary type "Audiobook"). The editions with as many tracks as
    the files come first, with their track list (chapter titles)."""
    query = f"release:{_lucene(title)} AND secondarytype:audiobook"
    if author:
        query += f" AND artist:{_lucene(author)}"
    data = await musicbrainz.search_releases(http, query, limit=MAX_RESULTS)
    found: list[BookCandidate] = []
    for release in _dicts(data.get("releases")):
        mbid, name = _str(release.get("id")), _str(release.get("title"))
        if not mbid or not name:
            continue
        authors, narrators = _credits(release)
        count = sum(int(m.get("track-count") or 0) for m in _dicts(release.get("media")))
        group = _dict(release.get("release-group"))
        found.append(
            BookCandidate(
                id=f"musicbrainz:{mbid}",
                source="MusicBrainz",
                title=name,
                authors=authors,
                narrators=narrators,
                year=_year(release.get("date")),
                url=f"https://musicbrainz.org/release/{mbid}",
                track_count=count or None,
                release_group_id=_str(group.get("id")),
            )
        )
    found.sort(key=lambda c: c.track_count != files)  # stable: MusicBrainz's order otherwise
    for candidate in [c for c in found if c.track_count == files][:MUSICBRAINZ_DETAILS]:
        await _musicbrainz_tracks(http, candidate)
    return found


async def _musicbrainz_tracks(http: httpx.AsyncClient, candidate: BookCandidate) -> None:
    mbid = candidate.id.removeprefix("musicbrainz:")
    release = await musicbrainz.release(http, mbid)
    if release is None:
        return
    tracks: list[dict[str, Any]] = []
    for medium in _dicts(release.get("media")):
        for track in _dicts(medium.get("tracks")):
            length = track.get("length")
            tracks.append(
                {
                    "title": _str(track.get("title")) or "",
                    "duration_ms": length if isinstance(length, int) else None,
                }
            )
    candidate.tracks = tracks
    durations = [t["duration_ms"] for t in tracks if t["duration_ms"]]
    if durations and len(durations) == len(tracks):
        candidate.duration_ms = sum(durations)
    if _dict(release.get("cover-art-archive")).get("front"):
        candidate.cover_url = f"https://coverartarchive.org/release/{mbid}/front-500"
