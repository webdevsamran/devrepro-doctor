"""Fleet analytics tests: distribution, segmentation, heatmap, compliance."""

from __future__ import annotations

from devrepro.core.versioning import satisfies
from devrepro.server.fleet import (
    baseline_compliance,
    fleet_segmentation,
    readiness_distribution,
    tool_version_heatmap,
)

_ROWS = [
    {
        "machine_key": "m1",
        "payload": {
            "verdict": "ready",
            "os_name": "Windows",
            "arch": "x86_64",
            "tools": {"python": "3.12.1", "node": "20.11.0"},
        },
    },
    {
        "machine_key": "m2",
        "payload": {
            "verdict": "ready_with_warnings",
            "os_name": "Windows",
            "arch": "x86_64",
            "tools": {"python": "3.11.4", "node": "18.19.0"},
        },
    },
    {
        "machine_key": "m3",
        "payload": {
            "verdict": "blocked",
            "os_name": "Linux",
            "arch": "aarch64",
            "tools": {"python": "3.10.9"},
        },
    },
]


def test_readiness_distribution() -> None:
    dist = readiness_distribution(_ROWS)
    assert dist == {"blocked": 1, "ready": 1, "ready_with_warnings": 1}


def test_fleet_segmentation_os_arch() -> None:
    seg = fleet_segmentation(_ROWS)
    # segments are keyed by (os, arch, verdict); aggregate per os/arch
    totals: dict[tuple[str, str], int] = {}
    for s in seg:
        k = (str(s["os"]), str(s["arch"]))
        totals[k] = totals.get(k, 0) + int(s["machines"])
    assert totals[("Windows", "x86_64")] == 2
    assert totals[("Linux", "aarch64")] == 1


def test_tool_version_heatmap_counts_versions() -> None:
    heat = tool_version_heatmap(_ROWS, ("python", "node"))
    assert heat["python"]["3.12.1"] == 1
    assert heat["python"]["3.11.4"] == 1
    assert heat["node"]["absent"] == 1


def test_baseline_compliance_flags_missing_and_mismatched() -> None:
    report = baseline_compliance(_ROWS, {"python": ">=3.11", "node": ">=20"}, satisfies)
    by_machine = {r["machine_key"]: r for r in report}
    # m1: both satisfied
    assert by_machine["m1"]["compliant"] is True
    # m2: node 18 < 20 required
    m2 = by_machine["m2"]
    assert m2["compliant"] is False
    assert m2["failures"][0]["tool"] == "node"
    # m3: node absent entirely
    m3 = by_machine["m3"]
    assert any(f["actual"] == "absent" for f in m3["failures"])  # type: ignore[union-attr]
