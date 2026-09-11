"""Onboarding bundle export.

Produces a single ``.tar.gz`` containing everything a teammate needs to
reproduce a working environment setup:

- ``report.json``          — the sanitized scan report (privacy-redacted)
- ``requirements.json``    — inferred project requirements summary
- ``setup-steps.md``       — exact ordered setup steps for THIS machine class
- ``manifest.json``        — bundle metadata + SHA-256 checksums of members

The bundle never contains secret values: callers must pass an already
sanitized report (the CLI pipeline redacts before export).
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["BUNDLE_FORMAT_VERSION", "build_onboarding_bundle"]

BUNDLE_FORMAT_VERSION = 1


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_setup_steps(report: dict[str, Any]) -> list[str]:
    """Derive ordered, machine-tailored setup steps from a sanitized report.

    Every read below was once addressed to a report shape this project does not
    produce, and the test fixture had been written to match the code rather than
    the scanner -- so it agreed, and `devrepro bundle` raised `AttributeError`
    on the first real report it ever saw.

    `tools` is a list of installations, not a mapping keyed by name. There is no
    `found` flag; a tool that resolves to nothing is absent, and one that
    resolves without a parseable version has `version: null`. The platform lives
    under `platform.os_name`, and `report.get("platform", "")` returned the
    whole dictionary, which `str()` would have pasted into the guide as the name
    of an operating system. And `state` is `BLOCKED`; comparing it to
    `"blocker"` meant this file had never once reported a blocker, and instead
    told every reader that none had been recorded.

    That last one is the reason this is worth more than a stack trace. A crash
    stops; a setup guide that says "no open blockers" on a machine with one is
    read, believed and acted on.
    """
    steps: list[str] = []
    platform = report.get("platform")
    os_name = str(platform.get("os_name", "") or "") if isinstance(platform, dict) else ""
    if os_name:
        steps.append(f"1. Confirm you are on the same OS family as the author: {os_name}.")

    raw_tools = report.get("tools") or []
    tools = [entry for entry in raw_tools if isinstance(entry, dict)]

    # Two installations of the same tool is the normal case on Windows, where an
    # App Execution Alias shadows a real interpreter. The active one is what the
    # author's machine actually ran, so that is the version to match.
    active: dict[str, str] = {}
    for entry in tools:
        name = str(entry.get("name") or "")
        version = entry.get("version")
        if name and version and (entry.get("is_active") or name not in active):
            active[name] = str(version)

    unversioned = sorted(
        {
            str(entry.get("name"))
            for entry in tools
            if entry.get("name") and not entry.get("version")
        }
        - set(active)
    )
    if unversioned:
        steps.append(
            "2. These resolved on the author's machine but reported no version, so pin "
            "them deliberately: " + ", ".join(unversioned) + "."
        )
    else:
        steps.append("2. Every toolchain found on the author's machine reported a version.")

    if active:
        pretty = ", ".join(f"{name} {version}" for name, version in sorted(active.items()))
        steps.append(f"3. Match tool versions where the project pins them: {pretty}.")

    findings = [f for f in (report.get("findings") or []) if isinstance(f, dict)]
    blockers = [f for f in findings if str(f.get("state", "")).upper() == "BLOCKED"]
    if blockers:
        steps.append(
            "4. Resolve known blockers first: "
            + "; ".join(str(b.get("rule_id", b.get("id", "?"))) for b in blockers[:5])
            + "."
        )
    else:
        steps.append("4. No open blockers were recorded in the sanitized report.")
    steps.append(
        "5. Run `devrepro preflight` after setup; it exits non-zero until the project is READY."
    )
    return steps


def build_onboarding_bundle(
    report: dict[str, Any],
    out_path: Path,
    *,
    requirements: dict[str, Any] | None = None,
    project_name: str = "",
) -> Path:
    """Write the onboarding bundle and return its path."""
    requirements = requirements if requirements is not None else {}
    now = datetime.now(UTC).isoformat()

    report_bytes = json.dumps(report, indent=2, default=str).encode("utf-8")
    req_bytes = json.dumps(requirements, indent=2, default=str).encode("utf-8")

    steps = build_setup_steps(report)
    nl = chr(10)
    md_lines = ["# Onboarding setup steps", "", f"_Generated {now}_", ""]
    md_lines += steps
    md_bytes = (nl.join(md_lines) + nl).encode("utf-8")

    manifest = {
        "format": "devrepro-onboarding-bundle",
        "format_version": BUNDLE_FORMAT_VERSION,
        "created_at": now,
        "project": project_name,
        "members": {},  # filled below
    }

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:

        def _add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(data))

        _add("report.json", report_bytes)
        _add("requirements.json", req_bytes)
        _add("setup-steps.md", md_bytes)

        manifest["members"] = {
            "report.json": _sha256(report_bytes),
            "requirements.json": _sha256(req_bytes),
            "setup-steps.md": _sha256(md_bytes),
        }
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        _add("manifest.json", manifest_bytes)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(buf.getvalue())
    return out_path
