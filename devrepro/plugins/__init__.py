"""Plugin system."""

from __future__ import annotations

from devrepro.plugins.loader import PLUGIN_GROUPS, list_plugins, load_plugins

__all__ = ["PLUGIN_GROUPS", "list_plugins", "load_plugins"]