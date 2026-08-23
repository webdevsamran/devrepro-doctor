"""Project baseline manifests and machine-vs-baseline diffing.

A baseline records an APPROVED sanitized environment expectation for a
project (tool versions, PATH hygiene, container state). Machines are then
diffed against it with severity + project-impact classification, enabling
team drift detection without exposing secret machine data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "Baseline",
    "BaselineDiff",
    "BaselineDiffEntry",
    "diff_against_baseline",
    "load_baseline",
    "save_baseline",
]

BASELINE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class Baseline:
    """Approved sanitized environment expectation for a project."""

    project_fingerprint: str
    created_at: str
    tools: dict[str, str] = field(default_factory=dict)  # name -> required spec
    required_env_names: tuple[str, ...] = ()
    require_docker: bool = False
    max_path_duplicates: int = 0
    notes: str = ""

    @property
    def baseline_id(self) -> str:
        payload = json.dumps(
            {
                "project": self.project_fingerprint,
                "tools": self.tools,
                "env": sorted(self.required_env_names),
                "docker": self.require_docker,
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "baseline_id": self.baseline_id,
            "project_fingerprint": self.project_fingerprint,
            "created_at": self.created_at,
            "tools": dict(self.tools),
            "required_env_names": list(self.required_env_names),
            "require_docker": self.require_docker,
            "max_path_duplicates": self.max_path_duplicates,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class BaselineDiffEntry:
    component: str  # tool | env | docker | path
    name: str
    severity: str  # ok | warn | blocker
    project_impact: str  # how this affects the project
    expected: str
    actual: str


@dataclass(frozen=True)
class BaselineDiff:
    baseline_id: str
    entries: tuple[BaselineDiffEntry, ...]

    @property
    def blockers(self) -> tuple[BaselineDiffEntry, ...]:
        return tuple(e for e in self.entries if e.severity == "blocker")

    @property
    def warnings(self) -> tuple[BaselineDiffEntry, ...]:
        return tuple(e for e in self.entries if e.severity == "warn")

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "entries": [
                {
                    "component": e.component,
                    "name": e.name,
                    "severity": e.severity,
                    "project_impact": e.project_impact,
                    "expected": e.expected,
                    "actual": e.actual,
                }
                for e in self.entries
            ],
        }


def save_baseline(baseline: Baseline, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(baseline.as_dict(), indent=2) + chr(10), encoding="utf-8")
    return target


def load_baseline(path: Path | str) -> Baseline:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = str(data.get("schema_version", "1.0"))
    if not version.startswith("1."):
        msg = f"unsupported baseline schema_version: {version}"
        raise ValueError(msg)
    return Baseline(
        project_fingerprint=str(data.get("project_fingerprint", "")),
        created_at=str(data.get("created_at", "")),
        tools={str(k): str(v) for k, v in (data.get("tools") or {}).items()},
        required_env_names=tuple(data.get("required_env_names") or ()),
        require_docker=bool(data.get("require_docker", False)),
        max_path_duplicates=int(data.get("max_path_duplicates", 0)),
        notes=str(data.get("notes", "")),
    )


def diff_against_baseline(
    baseline: Baseline,
    machine_tools: dict[str, str],
    machine_env_names: set[str],
    docker_available: bool,
    path_duplicates: int = 0,
) -> BaselineDiff:
    """Compare a machine's sanitized state against the approved baseline."""
    from devrepro.core.versioning import parse_spec, parse_version

    entries: list[BaselineDiffEntry] = []
    for tool, spec in sorted(baseline.tools.items()):
        actual = machine_tools.get(tool)
        if actual is None:
            entries.append(
                BaselineDiffEntry(
                    "tool",
                    tool,
                    "blocker",
                    f"project requires {tool} {spec}; not found on this machine",
                    spec,
                    "absent",
                )
            )
            continue
        try:
            ok = parse_spec(spec).satisfied_by(parse_version(actual))
        except Exception:
            ok = actual == spec
        entries.append(
            BaselineDiffEntry(
                "tool",
                tool,
                "ok" if ok else "blocker",
                (
                    f"{tool} {actual} satisfies {spec}"
                    if ok
                    else f"{tool} {actual} does not satisfy required {spec}"
                ),
                spec,
                actual,
            )
        )
    for name in baseline.required_env_names:
        present = name in machine_env_names
        entries.append(
            BaselineDiffEntry(
                "env",
                name,
                "ok" if present else "blocker",
                (
                    f"required env var {name} is declared"
                    if present
                    else f"required env var {name} is missing (value never inspected)"
                ),
                "declared",
                "declared" if present else "missing",
            )
        )
    if baseline.require_docker:
        entries.append(
            BaselineDiffEntry(
                "docker",
                "daemon",
                "ok" if docker_available else "blocker",
                (
                    "docker daemon reachable"
                    if docker_available
                    else "project baseline requires docker; daemon not reachable"
                ),
                "available",
                "available" if docker_available else "unavailable",
            )
        )
    if path_duplicates > baseline.max_path_duplicates:
        entries.append(
            BaselineDiffEntry(
                "path",
                "duplicates",
                "warn",
                f"{path_duplicates} duplicate PATH entries exceed baseline "
                f"maximum of {baseline.max_path_duplicates}",
                str(baseline.max_path_duplicates),
                str(path_duplicates),
            )
        )
    return BaselineDiff(baseline_id=baseline.baseline_id, entries=tuple(entries))


def new_baseline(
    project_fingerprint: str,
    tools: dict[str, str],
    required_env_names: tuple[str, ...] = (),
    require_docker: bool = False,
    notes: str = "",
) -> Baseline:
    return Baseline(
        project_fingerprint=project_fingerprint,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        tools=tools,
        required_env_names=required_env_names,
        require_docker=require_docker,
        notes=notes,
    )
