"""Search links: sites chosen by the admin (a store, a search engine...), each a URL
template searched with the album's artist and title. GET links are opened by the browser;
POST ones are a form the browser submits (so the admin's login on that site is used).
"""

import asyncio
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, quote_plus, urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic import Field as PydanticField

from app.plugins.base import (
    SAMPLE_ALBUM,
    AlbumLink,
    Field,
    Plugin,
    PluginContext,
    PluginSettingsError,
    WantedAlbum,
)
from app.plugins.search_links import icons

logger = logging.getLogger(__name__)

PLACEHOLDERS = ("query", "artist", "album", "year", "mbid")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_SITE_ID = re.compile(r"^[a-z0-9-]{1,40}$")
ICON_RETRY_AFTER = timedelta(days=7)
MAX_SITES = 50
SAMPLE = SAMPLE_ALBUM  # to check the templates


class Site(BaseModel):
    # camelCase like the rest of the web UI's JSON.
    model_config = ConfigDict(extra="ignore", populate_by_name=True, str_strip_whitespace=True)

    id: str = ""
    name: str
    enabled: bool = True
    method: Literal["GET", "POST"] = "GET"
    url: str
    body: str = ""  # POST: application/x-www-form-urlencoded, placeholders in values
    icon_url: str = PydanticField(default="", alias="iconUrl")  # optional, else found on the site


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sites: list[Site] = []

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


DEFAULT_SITES = [
    Site(id="duckduckgo", name="DuckDuckGo", url="https://duckduckgo.com/?q={query}"),
    Site(id="amazon-fr", name="Amazon.fr", url="https://www.amazon.fr/s?k={query}&i=popular"),
    Site(
        id="fnac",
        name="Fnac",
        url="https://www.fnac.com/SearchResult/ResultList.aspx?Search={query}&sft=1&sa=0",
    ),
]


def _values(album: WantedAlbum) -> dict[str, str]:
    return {
        "query": f"{album.artist} {album.title}",
        "artist": album.artist,
        "album": album.title,
        "year": album.year or "",
        "mbid": album.release_group_mbid or "",
    }


def _fill(template: str, values: dict[str, str], *, encode: bool) -> str:
    def value(match: re.Match[str]) -> str:
        text = values[match.group(1)]
        return quote_plus(text) if encode else text

    return _PLACEHOLDER.sub(value, template)


def _form(body: str) -> list[tuple[str, str]]:
    """The fields of a POST body as copied from the browser (still with placeholders)."""
    return parse_qsl(body, keep_blank_values=True)


def _check(site: Site) -> None:
    where = f"“{site.name or site.url}”"
    if not site.name:
        raise PluginSettingsError("Every site needs a name")
    templates = [site.url]
    if site.method == "POST":
        templates += [value for _, value in _form(site.body)]
    used = [name for template in templates for name in _PLACEHOLDER.findall(template)]
    unknown = sorted(set(used) - set(PLACEHOLDERS))
    if unknown:
        raise PluginSettingsError(f"{where}: unknown placeholder {{{unknown[0]}}}")
    if not used:
        raise PluginSettingsError(f"{where}: use at least one placeholder, e.g. {{query}}")
    parts = urlsplit(_fill(site.url, _values(SAMPLE), encode=True))
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PluginSettingsError(f"{where}: the URL must start with http:// or https://")
    if site.method == "POST" and not _form(site.body):
        raise PluginSettingsError(f"{where}: a POST search needs its form fields")
    if site.icon_url and urlsplit(site.icon_url).scheme not in ("http", "https"):
        raise PluginSettingsError(f"{where}: the icon URL must start with http:// or https://")


def _sites(settings: dict[str, Any]) -> list[Site]:
    return Settings.model_validate(settings).sites


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


class SearchLinks(Plugin):
    id = "search-links"
    name = "Search links"
    description = (
        "Links to search a missing album on sites you choose (stores, search engines). "
        "POST searches are sent by your browser, so your login on that site is used when "
        "its cookies allow it (use Try to check)."
    )
    enabled_by_default = True

    def fields(self) -> list[Field]:
        names = ", ".join(f"{{{p}}}" for p in PLACEHOLDERS)
        return [
            Field(
                key="sites",
                label="Sites",
                type="list",
                help=f"Placeholders: {names} ({{query}} is the artist and the album). "
                "Drag the sites to change their order in the menu.",
                item_label="name",
                id_key="id",
                icon_asset="icons/{id}",
                can_try=True,
                fields=[
                    Field(key="name", label="Name", type="text", placeholder="Fnac"),
                    Field(key="enabled", label="Enabled", type="boolean"),
                    Field(key="method", label="Method", type="select", options=["GET", "POST"]),
                    Field(
                        key="url",
                        label="URL",
                        type="text",
                        placeholder="https://www.example.com/search?q={query}",
                    ),
                    Field(
                        key="body",
                        label="Form fields (POST body)",
                        type="textarea",
                        placeholder="search={query}&go=Search",
                        help="As shown by the browser's developer tools (Network, the search "
                        "request's payload), with placeholders in the values.",
                        visible_when=("method", "POST"),
                    ),
                    Field(
                        key="iconUrl",
                        label="Icon URL",
                        type="text",
                        placeholder="Optional: found on the site otherwise",
                    ),
                ],
            )
        ]

    def default_settings(self) -> dict[str, Any]:
        return Settings(sites=DEFAULT_SITES).dump()

    def validate(self, settings: dict[str, Any]) -> dict[str, Any]:
        try:
            parsed = Settings.model_validate(settings)
        except ValidationError as error:
            first = error.errors()[0]
            where = ".".join(str(part) for part in first["loc"])
            raise PluginSettingsError(f"{where}: {first['msg']}") from None
        if len(parsed.sites) > MAX_SITES:
            raise PluginSettingsError(f"At most {MAX_SITES} sites")
        seen: set[str] = set()
        for site in parsed.sites:
            _check(site)
            if not _SITE_ID.match(site.id) or site.id in seen:
                site.id = secrets.token_hex(4)
            seen.add(site.id)
        return parsed.dump()

    def links(
        self, album: WantedAlbum, settings: dict[str, Any], *, include_disabled: bool = False
    ) -> list[AlbumLink]:
        values = _values(album)
        return [
            AlbumLink(
                label=site.name,
                url=_fill(site.url, values, encode=True),
                method=site.method,
                form=[
                    (name, _fill(value, values, encode=False)) for name, value in _form(site.body)
                ]
                if site.method == "POST"
                else [],
                icon=f"icons/{site.id}",
            )
            for site in _sites(settings)
            if site.enabled or include_disabled
        ]

    # --- icons --------------------------------------------------------------------

    @staticmethod
    def _icon_paths(context: PluginContext, site_id: str) -> tuple[Path, Path]:
        """(the icon, the marker saying none was found)."""
        folder = context.data_dir / "icons"
        return folder / f"{site_id}.png", folder / f"{site_id}.none"

    async def _ensure_icon(self, site: Site, context: PluginContext) -> str | None:
        """Fetches the site's icon if it has none; a warning if that failed."""
        icon, missing = self._icon_paths(context, site.id)
        if icon.is_file():
            return None
        if missing.is_file():
            age = datetime.now(UTC) - datetime.fromtimestamp(missing.stat().st_mtime, UTC)
            if age < ICON_RETRY_AFTER:
                return None
        site_url = _fill(site.url, _values(SAMPLE), encode=True)
        try:
            data = await icons.fetch(context.http, site_url, site.icon_url or None)
        except icons.IconError as error:
            await asyncio.to_thread(_write, missing, b"")
            logger.info("No icon for %s: %s", site.name, error)
            return f"No icon for “{site.name}”: {error}"
        await asyncio.to_thread(_write, icon, data)
        await asyncio.to_thread(missing.unlink, missing_ok=True)
        return None

    async def saved(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        context: PluginContext,
        *,
        refresh: bool = False,
    ) -> list[str]:
        before = {site.id: site for site in _sites(old)}
        sites = _sites(new)

        def forget(site_id: str) -> None:
            for path in self._icon_paths(context, site_id):
                path.unlink(missing_ok=True)

        for site in sites:  # a new host or icon URL: a new icon
            previous = before.get(site.id)
            same = previous is not None and (
                urlsplit(previous.url).netloc == urlsplit(site.url).netloc
                and previous.icon_url == site.icon_url
            )
            if refresh or not same:
                await asyncio.to_thread(forget, site.id)
        for site_id in set(before) - {site.id for site in sites}:
            await asyncio.to_thread(forget, site_id)
        warnings = await asyncio.gather(*(self._ensure_icon(site, context) for site in sites))
        return [warning for warning in warnings if warning]

    async def asset(
        self, name: str, settings: dict[str, Any], context: PluginContext
    ) -> tuple[Path, str] | None:
        if not name.startswith("icons/"):
            return None
        site_id = name.removeprefix("icons/")
        site = next((s for s in _sites(settings) if s.id == site_id), None)
        if site is None:
            return None
        await self._ensure_icon(site, context)  # e.g. the default sites, never saved
        icon, _ = self._icon_paths(context, site.id)
        return (icon, "image/png") if icon.is_file() else None
