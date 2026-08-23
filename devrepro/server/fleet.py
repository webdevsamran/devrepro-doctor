"""Fleet analytics: readiness distribution, segmentation, baseline compliance.

Pure functions over stored snapshot payloads so the frontend can render
fleet dashboards without exposing any secret machine data. All inputs are
already-sanitized snapshot dicts.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

__all__ = [
    "baseline_compliance",
    "fleet_segmentation",
    "readiness_distribution",
    "tool_version_heatmap",
]


def _snapshots_by_machine(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest snapshot payload per machine_key."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:  # rows are ordered newest-first by the store
        key = str(row.get("machine_key"))
        if key and key not in out and isinstance(row.get("payload"), dict):
            out[key] = row["payload"]
        elif key not in out and isinstance(row.get("snapshot"), dict):
            out[key] = row["snapshot"]
    return out


def readiness_distribution(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    """Count of machines per verdict (ready / warnings / blocked / unknown)."""
    dist: Counter[str] = Counter()
    for snap in _snapshots_by_machine(rows).values():
        verdict = str(snap.get("verdict") or snap.get("worst_state") or "unknown")
        dist[verdict.lower()] += 1
    return dict(sorted(dist.items()))


def fleet_segmentation(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Segment machines by OS x architecture x readiness."""
    seg: Counter[tuple[str, str, str]] = Counter()
    for _key, snap in _snapshots_by_machine(rows).items():
        raw_platform = snap.get("platform")
        platform: dict[str, Any] = dict(raw_platform) if isinstance(raw_platform, dict) else {}
        os_name = str(snap.get("os_name") or platform.get("os_name", "unknown"))
        arch = str(snap.get("arch") or platform.get("arch", "unknown"))
        verdict = str(snap.get("verdict") or "unknown").lower()
        seg[(os_name, arch, verdict)] += 1
    return [
        {"os": o, "arch": a, "verdict": v, "machines": n} for (o, a, v), n in sorted(seg.items())
    ]


def tool_version_heatmap(
    rows: list[dict[str, Any]], tools: tuple[str, ...]
) -> dict[str, dict[str, int]]:
    """For each requested tool, count of machines per observed version."""
    heat: dict[str, Counter[str]] = {t: Counter() for t in tools}
    for snap in _snapshots_by_machine(rows).values():
        versions = snap.get("tools") or snap.get("tool_versions") or {}
        if not isinstance(versions, dict):
            continue
        for t in tools:
            ver = versions.get(t)
            heat[t][str(ver or "absent")] += 1
    return {t: dict(c.most_common()) for t, c in heat.items()}


def baseline_compliance(
    rows: list[dict[str, Any]],
    baseline_tools: dict[str, str],
    satisfies_fn: Any,
) -> list[dict[str, object]]:
    """Per-machine pass/fail against an approved baseline's tool pins.

    ``satisfies_fn(version, spec)`` is devrepro.core.versioning.satisfies.
    Machines missing a required tool count as non-compliant for it.
    """
    report: list[dict[str, object]] = []
    for machine_key, snap in sorted(_snapshots_by_machine(rows).items()):
        versions = snap.get("tools") or snap.get("tool_versions") or {}
        if not isinstance(versions, dict):
            versions = {}
        failures: list[dict[str, str]] = []
        for name, spec in baseline_tools.items():
            actual = versions.get(name)
            if actual is None:
                failures.append({"tool": name, "expected": spec, "actual": "absent"})
                continue
            try:
                ok = bool(satisfies_fn(str(actual), spec))
            except Exception:
                ok = False
            if not ok:
                failures.append({"tool": name, "expected": spec, "actual": str(actual)})
        report.append(
            {
                "machine_key": machine_key,
                "compliant": not failures,
                "failures": failures,
            }
        )
    return report
