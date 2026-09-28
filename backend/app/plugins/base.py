"""The plugin contract.

A plugin is a class with an identity, the fields of its settings form (rendered by the web
UI's Settings page, no plugin-specific frontend code) and one or more capabilities. The
only capability for now is `LinkProvider`: links for an album the library does not have.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import httpx

FieldType = Literal["text", "textarea", "boolean", "select", "list"]


class PluginSettingsError(ValueError):
    """Settings a plugin refuses (shown to the admin)."""


@dataclass
class Field:
    """A settings field. `list` fields have sub-fields (`fields`), one row per item."""

    key: str
    label: str
    type: FieldType
    help: str | None = None
    placeholder: str | None = None
    options: list[str] = field(default_factory=list[str])  # select
    # Shown only when the sibling field `visible_when[0]` equals `visible_when[1]`.
    visible_when: tuple[str, str] | None = None
    # list
    fields: list["Field"] = field(default_factory=list["Field"])
    item_label: str | None = None  # the sub-field naming a row
    id_key: str | None = None  # the sub-field identifying a row (set by the plugin)
    icon_asset: str | None = None  # asset name of a row's icon, "{id}" replaced
    can_try: bool = False  # a "Try" button per row (plugins with links)


@dataclass
class PluginContext:
    """What a plugin may use besides its settings."""

    http: httpx.AsyncClient
    data_dir: Path  # <data>/plugins/<plugin id>/, created when needed


@dataclass
class WantedAlbum:
    """An album to find. Nothing about the user."""

    artist: str
    title: str
    year: str | None
    release_group_mbid: str | None = None
    artist_mbid: str | None = None


# The album "Try" buttons search for (Settings).
SAMPLE_ALBUM = WantedAlbum(artist="Amon Amarth", title="Berserker", year="2019")


@dataclass
class AlbumLink:
    label: str
    url: str
    method: Literal["GET", "POST"] = "GET"
    form: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])  # POST fields
    icon: str | None = None  # asset name


class Plugin(ABC):
    id: str
    name: str
    description: str
    enabled_by_default: bool = False

    @abstractmethod
    def fields(self) -> list[Field]: ...

    @abstractmethod
    def default_settings(self) -> dict[str, Any]: ...

    @abstractmethod
    def validate(self, settings: dict[str, Any]) -> dict[str, Any]:
        """The settings to store (defaults filled, ids given); PluginSettingsError if
        they are wrong."""

    async def saved(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        context: PluginContext,
        *,
        refresh: bool = False,  # fetch again what the plugin keeps (e.g. icons)
    ) -> list[str]:
        """Called after new settings were stored; returns warnings for the admin."""
        return []

    async def asset(
        self, name: str, settings: dict[str, Any], context: PluginContext
    ) -> tuple[Path, str] | None:
        """(file, content type) of a file the plugin serves (e.g. icons)."""
        return None


@runtime_checkable
class LinkProvider(Protocol):
    """Capability: links for an album (search pages, stores...)."""

    def links(
        self,
        album: WantedAlbum,
        settings: dict[str, Any],
        *,
        include_disabled: bool = False,  # "Try" in Settings: a row not enabled yet
    ) -> list[AlbumLink]: ...
