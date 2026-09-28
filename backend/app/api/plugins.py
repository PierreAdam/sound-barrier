"""Plugins (admins): their settings, rendered by the web UI from the fields each plugin
declares, and the files they serve."""

from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.deps import AdminCaller, ApiModel, DbSession
from app.core.config import Settings
from app.plugins import PLUGINS, capabilities
from app.plugins.base import (
    SAMPLE_ALBUM,
    AlbumLink,
    Field,
    LinkProvider,
    Plugin,
    PluginSettingsError,
)
from app.services import plugins

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _data_dir(request: Request) -> Path:
    settings: Settings = request.app.state.settings
    return settings.data_dir


def _plugin(plugin_id: str) -> Plugin:
    plugin = PLUGINS.get(plugin_id)
    if plugin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown plugin")
    return plugin


class FieldOut(ApiModel):
    key: str
    label: str
    type: str
    help: str | None
    placeholder: str | None
    options: list[str]
    visible_when: tuple[str, str] | None
    fields: list["FieldOut"]
    item_label: str | None
    id_key: str | None
    icon_asset: str | None
    can_try: bool


def _field(field: Field) -> FieldOut:
    values = asdict(field)
    values["fields"] = [_field(sub) for sub in field.fields]
    return FieldOut(**values)


class PluginOut(ApiModel):
    id: str
    name: str
    description: str
    capabilities: list[str]
    fields: list[FieldOut]
    enabled: bool
    # The plugin's own keys (its fields' `key`), sent as they are.
    settings: dict[str, Any]


class SavedPluginOut(ApiModel):
    plugin: PluginOut
    warnings: list[str]


class PluginIn(ApiModel):
    enabled: bool
    settings: dict[str, Any]
    refresh: bool = False  # fetch again what the plugin keeps (e.g. icons)


class TryIn(ApiModel):
    settings: dict[str, Any]
    field: str  # the list field
    item: int  # the row


class LinkOut(ApiModel):
    label: str
    url: str
    method: str
    form: list[tuple[str, str]]
    icon_url: str | None


def link_out(plugin: Plugin, link: AlbumLink) -> LinkOut:
    return LinkOut(
        label=link.label,
        url=link.url,
        method=link.method,
        form=link.form,
        icon_url=f"/api/plugins/{plugin.id}/assets/{link.icon}" if link.icon else None,
    )


def _out(state: plugins.PluginState) -> PluginOut:
    plugin = state.plugin
    return PluginOut(
        id=plugin.id,
        name=plugin.name,
        description=plugin.description,
        capabilities=capabilities(plugin),
        fields=[_field(f) for f in plugin.fields()],
        enabled=state.enabled,
        settings=state.settings,
    )


@router.get("")
async def list_plugins(_: AdminCaller, session: DbSession) -> list[PluginOut]:
    return [_out(state) for state in await plugins.get_all(session)]


@router.put("/{plugin_id}")
async def save_plugin(
    plugin_id: str, body: PluginIn, request: Request, _: AdminCaller, session: DbSession
) -> SavedPluginOut:
    plugin = _plugin(plugin_id)
    context = plugins.context(plugin, request.app.state.http, _data_dir(request))
    try:
        state, warnings = await plugins.save(
            session, plugin, body.enabled, body.settings, context, refresh=body.refresh
        )
    except PluginSettingsError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    await session.commit()
    return SavedPluginOut(plugin=_out(state), warnings=warnings)


@router.post("/{plugin_id}/try")
async def try_plugin(plugin_id: str, body: TryIn, _: AdminCaller) -> list[LinkOut]:
    """The links of one row of a list field (saved or not), for a sample album."""
    plugin = _plugin(plugin_id)
    if not isinstance(plugin, LinkProvider):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This plugin gives no links")
    rows: Any = body.settings.get(body.field)
    items = cast(list[Any], rows) if isinstance(rows, list) else []
    if not 0 <= body.item < len(items):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown row")
    try:
        settings = plugin.validate({**body.settings, body.field: [items[body.item]]})
    except PluginSettingsError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    return [
        link_out(plugin, link)
        for link in plugin.links(SAMPLE_ALBUM, settings, include_disabled=True)
    ]


@router.get("/{plugin_id}/assets/{name:path}")
async def plugin_asset(
    plugin_id: str, name: str, request: Request, _: AdminCaller, session: DbSession
) -> FileResponse:
    plugin = _plugin(plugin_id)
    state = await plugins.get(session, plugin)
    context = plugins.context(plugin, request.app.state.http, _data_dir(request))
    found = await plugin.asset(name, state.settings, context)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file")
    path, content_type = found
    return FileResponse(
        path, media_type=content_type, headers={"Cache-Control": "private, no-cache"}
    )
