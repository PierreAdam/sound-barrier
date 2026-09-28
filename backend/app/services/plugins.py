"""Plugin settings (stored in `server_setting` under `plugin:<id>`) and the calls to the
plugins' capabilities."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServerSetting
from app.plugins import PLUGINS
from app.plugins.base import AlbumLink, LinkProvider, Plugin, PluginContext, WantedAlbum

logger = logging.getLogger(__name__)


@dataclass
class PluginState:
    plugin: Plugin
    enabled: bool
    settings: dict[str, Any]


@dataclass
class PluginLinks:
    plugin: Plugin
    links: list[AlbumLink]


def _key(plugin: Plugin) -> str:
    return f"plugin:{plugin.id}"


def context(plugin: Plugin, http: httpx.AsyncClient, data_dir: Path) -> PluginContext:
    return PluginContext(http=http, data_dir=data_dir / "plugins" / plugin.id)


async def get(session: AsyncSession, plugin: Plugin) -> PluginState:
    row = await session.get(ServerSetting, _key(plugin))
    if row is None:
        return PluginState(plugin, plugin.enabled_by_default, plugin.default_settings())
    value: dict[str, Any] = row.value
    try:
        settings = plugin.validate(value.get("settings") or plugin.default_settings())
    except ValueError:
        logger.warning("Invalid settings stored for plugin %s, using defaults", plugin.id)
        settings = plugin.default_settings()
    return PluginState(plugin, bool(value.get("enabled")), settings)


async def get_all(session: AsyncSession) -> list[PluginState]:
    return [await get(session, plugin) for plugin in PLUGINS.values()]


async def save(
    session: AsyncSession,
    plugin: Plugin,
    enabled: bool,
    settings: dict[str, Any],
    plugin_context: PluginContext,
    *,
    refresh: bool = False,
) -> tuple[PluginState, list[str]]:
    """Validates (PluginSettingsError) and stores the settings; returns the plugin's
    warnings. The caller commits."""
    before = await get(session, plugin)
    validated = plugin.validate(settings)
    value = {"enabled": enabled, "settings": validated}
    statement = insert(ServerSetting).values(key=_key(plugin), value=value)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[ServerSetting.key], set_={"value": value})
    )
    warnings = await plugin.saved(before.settings, validated, plugin_context, refresh=refresh)
    return PluginState(plugin, enabled, validated), warnings


async def album_links(session: AsyncSession, album: WantedAlbum) -> list[PluginLinks]:
    """The links of every enabled plugin that gives links, in the registry's order."""
    found: list[PluginLinks] = []
    for state in await get_all(session):
        if state.enabled and isinstance(state.plugin, LinkProvider):
            links = state.plugin.links(album, state.settings)
            if links:
                found.append(PluginLinks(state.plugin, links))
    return found
