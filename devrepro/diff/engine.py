"""Environment diff engine: compare two snapshots and classify every
difference. This is the signature "works on my machine" feature.
"""

from __future__ import annotations

from devrepro.core.errors import DiffError
from devrepro.core.models import (
    DiffClassification,
    DiffEntry,
    EnvironmentDiff,
    Snapshot,
)

__all__ = ["diff_snapshots"]

_PLATFORM_KEYS = {"os_name", "os_version", "arch", "kernel"}


def diff_snapshots(a: Snapshot, b: Snapshot) -> EnvironmentDiff:
    if a.schema_version != b.schema_version:
        raise DiffError(
            f"incompatible snapshot schema versions: {a.schema_version} vs {b.schema_version}"
        )

    entries: list[DiffEntry] = []

    # ---- platform ---------------------------------------------------------
    pa, pb = a.platform, b.platform
    for key in _PLATFORM_KEYS:
        va, vb = getattr(pa, key), getattr(pb, key)
        if va != vb:
            entries.append(
                DiffEntry(
                    component="platform",
                    name=key,
                    classification=DiffClassification.PLATFORM_EXPECTED,
                    a_value=str(va),
                    b_value=str(vb),
                    detail="Platform differences are expected across machines; "
                    "only flag if the project targets one OS.",
                )
            )

    # ---- tools ---------------------------------------------------------------
    a_tools = {t.name: t for t in a.tools}
    b_tools = {t.name: t for t in b.tools}
    critical_names = {r.name for r in a.requirements_fingerprint} | {
        r.name for r in b.requirements_fingerprint
    }
    for name in sorted(set(a_tools) | set(b_tools)):
        ta, tb = a_tools.get(name), b_tools.get(name)
        critical = name in critical_names
        if ta is None and tb is not None:
            entries.append(DiffEntry(
                component="tool", name=name,
                classification=DiffClassification.MISSING if critical else DiffClassification.MISSING,
                a_value=None, b_value=tb.version,
                detail=f"'{name}' exists on B but not on A.",
                project_critical=critical,
            ))
        elif tb is None and ta is not None:
            entries.append(DiffEntry(
                component="tool", name=name,
                classification=DiffClassification.MISSING,
                a_value=ta.version, b_value=None,
                detail=f"'{name}' exists on A but not on B.",
                project_critical=critical,
            ))
        elif ta is not None and tb is not None:
            if (ta.version or "") != (tb.version or ""):
                entries.append(DiffEntry(
                    component="tool", name=name,
                    classification=DiffClassification.VERSION_DRIFT,
                    a_value=ta.version, b_value=tb.version,
                    detail=f"Version drift on '{name}'.",
                    project_critical=critical,
                ))
            elif (ta.exe_path or "") != (tb.exe_path or ""):
                entries.append(DiffEntry(
                    component="tool", name=name,
                    classification=DiffClassification.PATH_PRECEDENCE,
                    a_value=ta.exe_path, b_value=tb.exe_path,
                    detail=f"'{name}' resolves to different executables (same version).",
                    project_critical=critical,
                ))
            else:
                entries.append(DiffEntry(
                    component="tool", name=name,
                    classification=DiffClassification.SAME,
                    a_value=ta.version, b_value=tb.version,
                ))

    # ---- PATH precedence ---------------------------------------------------------
    pa_entries = a.path_analysis.entries if a.path_analysis else ()
    pb_entries = b.path_analysis.entries if b.path_analysis else ()
    a_norm = [e.normalized for e in pa_entries]
    b_norm = [e.normalized for e in pb_entries]
    if a_norm != b_norm:
        only_a = [p for p in a_norm if p not in b_norm]
        only_b = [p for p in b_norm if p not in a_norm]
        entries.append(DiffEntry(
            component="path",
            name="PATH",
            classification=DiffClassification.PATH_PRECEDENCE,
            a_value=f"{len(a_norm)} entries" + (f"; A-only: {len(only_a)}" if only_a else ""),
            b_value=f"{len(b_norm)} entries" + (f"; B-only: {len(only_b)}" if only_b else ""),
            detail="PATH composition differs; resolution order may differ even for "
            "identical tool versions.",
        ))

    # ---- requirements fingerprint ---------------------------------------------------
    a_reqs = {(r.ecosystem, r.name): r.spec for r in a.requirements_fingerprint}
    b_reqs = {(r.ecosystem, r.name): r.spec for r in b.requirements_fingerprint}
    for key in sorted(set(a_reqs) | set(b_reqs)):
        va, vb = a_reqs.get(key), b_reqs.get(key)
        if va != vb:
            entries.append(DiffEntry(
                component="requirement",
                name=":".join(key),
                classification=DiffClassification.PROJECT_CRITICAL,
                a_value=va, b_value=vb,
                detail="Declared project requirements differ between the two snapshots.",
                project_critical=True,
            ))

    # ---- containers / wsl / gpu ---------------------------------------------------------
    if (a.containers is None) != (b.containers is None) or (
        a.containers and b.containers
        and a.containers.docker_daemon_ok != b.containers.docker_daemon_ok
    ):
        entries.append(DiffEntry(
            component="container", name="docker-daemon",
            classification=DiffClassification.PROJECT_CRITICAL,
            a_value=str(a.containers.docker_daemon_ok if a.containers else None),
            b_value=str(b.containers.docker_daemon_ok if b.containers else None),
            detail="Docker daemon health differs; container builds will behave differently.",
            project_critical=True,
        ))

    return EnvironmentDiff(
        a_snapshot_id=a.snapshot_id,
        b_snapshot_id=b.snapshot_id,
        entries=tuple(entries),
    )