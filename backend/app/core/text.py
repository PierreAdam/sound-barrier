import re
import unicodedata

# Subsonic's default `ignoredArticles`.
IGNORED_ARTICLES = ("The", "El", "La", "Los", "Las", "Le", "Les")


def normalize(value: str) -> str:
    """Lowercase, accent-free, whitespace-collapsed form used for search and matching."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def strip_articles(value: str, articles: tuple[str, ...] = IGNORED_ARTICLES) -> str:
    for article in articles:
        prefix = article + " "
        if value[: len(prefix)].casefold() == prefix.casefold() and len(value) > len(prefix):
            return value[len(prefix) :]
    return value


def sort_key(value: str) -> str:
    """Sort form: articles stripped, then normalized."""
    return normalize(strip_articles(value.strip()))


def index_letter(sort_name: str) -> str:
    """First letter for artist indexes (`getArtists`, `getIndexes`); `#` for non-letters."""
    first = normalize(sort_name)[:1].upper()
    return first if first.isalpha() else "#"


_BRACKETS = re.compile(r"[\(\[].*?[\)\]]")
_PUNCTUATION = re.compile(r"[^\w\s]")


def title_key(title: str) -> str:
    """Matching form of a song or album title: "Blinded by Fear (Remastered)" and
    "Blinded By Fear" are the same song, "Deceiver of the Gods [Deluxe Edition]" and
    "Deceiver of the Gods" the same album."""
    return normalize(_PUNCTUATION.sub(" ", _BRACKETS.sub(" ", title)))


def natural_key(value: str) -> list[tuple[int, int | str]]:
    """ "CH2" before "CH10": the numbers in a name compare as numbers."""
    return [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", value.casefold())
        if part
    ]


def consistent_numbers(numbers: list[tuple[int | None, int | None]]) -> bool:
    """Whether (disc, track) numbers can give an order: all tracks present, no two the
    same on a disc, none above the number of tracks of its disc. Audiobooks often carry
    leftovers of a CD rip instead (chapter 1 track 1, chapter 2 track 29...)."""
    discs: dict[int, list[int]] = {}
    for disc, track in numbers:
        if not track:
            return False
        discs.setdefault(disc or 1, []).append(track)
    return all(
        len(set(tracks)) == len(tracks) and max(tracks) <= len(tracks) for tracks in discs.values()
    )
