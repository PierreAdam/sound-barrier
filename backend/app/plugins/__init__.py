"""Embedded plugins (one sub-package each). Adding one: its package, and a line here.
The contract is in `base.py`."""

from app.plugins.base import LinkProvider, Plugin
from app.plugins.search_links import SearchLinks

PLUGINS: dict[str, Plugin] = {p.id: p for p in (SearchLinks(),)}


def capabilities(plugin: Plugin) -> list[str]:
    return ["links"] if isinstance(plugin, LinkProvider) else []
