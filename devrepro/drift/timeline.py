"""Drift timelines and root-cause hints across snapshot history.

Given an ordered list of snapshots (oldest first), produce:
- a timeline of component changes between consecutive snapshots;
- root-cause hints: for a failing snapshot, the FIRST earlier snapshot in
  which a relevant component changed (the classic "what changed?" answer).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["DriftEvent", "DriftTimeline", "build_timeline", "root_cause_hints"]


@dataclass(frozen=True)
class DriftEvent:
    at_index: int  # index into the input snapshot list (transition i-1 -> i)
    component: str  # tool | path | container | wsl | gpu | platform | score
    name: str
    kind: str  # added | removed | version-changed | precedence-changed | state-changed
    before: str | None
    after: str | None


@dataclass(frozen=True)
class DriftTimeline:
    events: tuple[DriftEvent, ...]
    snapshot_ids: tuple[str, ...]

    def changes_for(self, component: str, name: str) -> tuple[DriftEvent, ...]:
        return tuple(e for e in self.events if e.component == component and e.name == name)


def _tool_map(snapshot: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in snapshot.get("tools", []) or []:
        if isinstance(t, dict) and t.get("name"):
            out[str(t["name"])] = str(t.get("version") or "?")
    return out


def _container_state(snapshot: dict[str, Any]) -> dict[str, str]:
    c = snapshot.get("containers") or {}
    if not isinstance(c, dict):
        return {}
    return {
        "docker-daemon": "ok" if c.get("docker_daemon_ok") else "down",
        "docker-cli": str(c.get("docker_cli_version") or "-"),
        "podman": str(c.get("podman_version") or "-"),
    }


def build_timeline(snapshots: list[dict[str, Any]]) -> DriftTimeline:
    """Build a drift timeline from oldest->newest sanitized snapshot dicts."""
    events: list[DriftEvent] = []
    ids = tuple(
        str(s.get("snapshot_id", s.get("created_at", f"#{i}"))) for i, s in enumerate(snapshots)
    )
    prev_tools: dict[str, str] = {}
    prev_containers: dict[str, str] = {}
    for i, snap in enumerate(snapshots):
        tools = _tool_map(snap)
        for name in sorted(set(prev_tools) | set(tools)):
            b, a = prev_tools.get(name), tools.get(name)
            if b is None and a is not None:
                events.append(DriftEvent(i, "tool", name, "added", None, a))
            elif a is None and b is not None:
                events.append(DriftEvent(i, "tool", name, "removed", b, None))
            elif a != b and a is not None and b is not None:
                events.append(DriftEvent(i, "tool", name, "version-changed", b, a))
        cont = _container_state(snap)
        for key in sorted(set(prev_containers) | set(cont)):
            b, a = prev_containers.get(key), cont.get(key)
            if b != a and (b is not None or a is not None):
                events.append(DriftEvent(i, "container", key, "state-changed", b, a))
        prev_tools, prev_containers = tools, cont
    return DriftTimeline(events=tuple(events), snapshot_ids=ids)


def root_cause_hints(
    timeline: DriftTimeline,
    failing_component: str,
    failing_name: str,
) -> tuple[DriftEvent, ...]:
    """First transitions where a relevant component changed.

    A hint answers: "this component last changed between snapshots X and Y" —
    the prime suspect window for a new failure.
    """
    changes = timeline.changes_for(failing_component, failing_name)
    if changes:
        # the MOST RECENT transition where it changed is the prime suspect
        return (changes[-1],)
    # no direct change: surface any tool changes in the same transition window
    if timeline.events:
        last = timeline.events[-1].at_index
        related = tuple(e for e in timeline.events if e.at_index == last and e.component == "tool")
        return related[:3]
    return ()
