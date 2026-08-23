"""Plugin discovery across the five entry-point groups."""

from __future__ import annotations

from typing import Any

from devrepro.core.errors import PluginError

__all__ = ["PLUGIN_GROUPS", "list_plugins", "load_plugins"]

PLUGIN_GROUPS: tuple[str, ...] = (
    "devrepro.probes",
    "devrepro.rules",
    "devrepro.remediations",
    "devrepro.project_detectors",
    "devrepro.exporters",
)

API_VERSION = "1"


def _entry_points(group: str) -> list[Any]:
    from importlib.metadata import entry_points

    return list(entry_points(group=group))
    raise PluginError("Python <3.10 unsupported")


def list_plugins() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for group in PLUGIN_GROUPS:
        names: list[str] = []
        try:
            for ep in _entry_points(group):
                names.append(f"{ep.name} = {ep.value}")
        except Exception:
            continue
        out[group] = names
    return out


def load_plugins(group: str) -> list[tuple[str, Any]]:
    if group not in PLUGIN_GROUPS:
        raise PluginError(f"unknown plugin group {group!r}")
    loaded: list[tuple[str, Any]] = []
    for ep in _entry_points(group):
        try:
            obj = ep.load()
        except Exception as exc:
            raise PluginError(f"plugin {ep.name!r} failed to load: {exc}") from exc
        loaded.append((ep.name, obj))
    return loaded
