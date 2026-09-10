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


def _compare_optional(
    entries: list[DiffEntry],
    *,
    component: str,
    name: str,
    a_value: object,
    b_value: object,
    classification: DiffClassification,
    detail: str,
    project_critical: bool = False,
) -> None:
    """Append a DiffEntry when two optional values differ.

    Both sides being absent is not a difference -- neither machine reported the
    capability, which is silence, not drift.
    """
    if a_value == b_value or (a_value is None and b_value is None):
        return
    entries.append(
        DiffEntry(
            component=component,
            name=name,
            classification=classification,
            a_value=str(a_value),
            b_value=str(b_value),
            detail=detail,
            project_critical=project_critical,
        )
    )


#: Container-engine facts worth reporting when two snapshots disagree, with the
#: reason the difference matters. `project_critical` is reserved for the ones
#: that change whether a build *works* rather than how fast it runs -- a
#: different engine and a different architecture change behaviour; a version
#: number usually does not.
_CONTAINER_AXES: tuple[tuple[str, str, str, str, bool], ...] = (
    (
        "engine-backend",
        "backend",
        "backend",
        "A different container engine is behind `docker`. Bind-mount behaviour, "
        "file-sharing performance and available host paths all differ between them.",
        True,
    ),
    (
        "engine-arch",
        "server_arch",
        "server_arch",
        "The engines run different architectures; one of these is emulating, which "
        "is correct and roughly ten times slower.",
        True,
    ),
    (
        "cgroup-version",
        "cgroup_version",
        "cgroup_version",
        "cgroup versions differ. Memory and CPU limits behave differently, so a "
        "container that is OOM-killed on one machine can pass on the other.",
        True,
    ),
    (
        "storage-driver",
        "storage_driver",
        "storage_driver",
        "Storage drivers differ. Layer caching and build times differ with them, and "
        "some drivers are removed in current engines.",
        False,
    ),
    (
        "engine-version",
        "server_version",
        "server_version",
        "Container engine versions differ.",
        False,
    ),
    (
        "buildx-version",
        "buildx_version",
        "buildx_version",
        "buildx versions differ. Multi-platform builds, build secrets and cache "
        "mounts depend on it.",
        False,
    ),
    (
        "rootless",
        "rootless",
        "rootless",
        "One engine runs rootless and the other does not. Port binding below 1024, "
        "file ownership in bind mounts and some network modes differ.",
        True,
    ),
)


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
            entries.append(
                DiffEntry(
                    component="tool",
                    name=name,
                    classification=DiffClassification.MISSING,
                    a_value=None,
                    b_value=tb.version,
                    detail=f"'{name}' exists on B but not on A.",
                    project_critical=critical,
                )
            )
        elif tb is None and ta is not None:
            entries.append(
                DiffEntry(
                    component="tool",
                    name=name,
                    classification=DiffClassification.MISSING,
                    a_value=ta.version,
                    b_value=None,
                    detail=f"'{name}' exists on A but not on B.",
                    project_critical=critical,
                )
            )
        elif ta is not None and tb is not None:
            if (ta.version or "") != (tb.version or ""):
                entries.append(
                    DiffEntry(
                        component="tool",
                        name=name,
                        classification=DiffClassification.VERSION_DRIFT,
                        a_value=ta.version,
                        b_value=tb.version,
                        detail=f"Version drift on '{name}'.",
                        project_critical=critical,
                    )
                )
            elif (ta.exe_path or "") != (tb.exe_path or ""):
                entries.append(
                    DiffEntry(
                        component="tool",
                        name=name,
                        classification=DiffClassification.PATH_PRECEDENCE,
                        a_value=ta.exe_path,
                        b_value=tb.exe_path,
                        detail=f"'{name}' resolves to different executables (same version).",
                        project_critical=critical,
                    )
                )
            else:
                entries.append(
                    DiffEntry(
                        component="tool",
                        name=name,
                        classification=DiffClassification.SAME,
                        a_value=ta.version,
                        b_value=tb.version,
                    )
                )

    # ---- PATH precedence ---------------------------------------------------------
    pa_entries = a.path_analysis.entries if a.path_analysis else ()
    pb_entries = b.path_analysis.entries if b.path_analysis else ()
    a_norm = [e.normalized for e in pa_entries]
    b_norm = [e.normalized for e in pb_entries]
    if a_norm != b_norm:
        only_a = [p for p in a_norm if p not in b_norm]
        only_b = [p for p in b_norm if p not in a_norm]
        entries.append(
            DiffEntry(
                component="path",
                name="PATH",
                classification=DiffClassification.PATH_PRECEDENCE,
                a_value=f"{len(a_norm)} entries" + (f"; A-only: {len(only_a)}" if only_a else ""),
                b_value=f"{len(b_norm)} entries" + (f"; B-only: {len(only_b)}" if only_b else ""),
                detail="PATH composition differs; resolution order may differ even for "
                "identical tool versions.",
            )
        )

    # ---- requirements fingerprint ---------------------------------------------------
    a_reqs = {(r.ecosystem, r.name): r.spec for r in a.requirements_fingerprint}
    b_reqs = {(r.ecosystem, r.name): r.spec for r in b.requirements_fingerprint}
    for req_key in sorted(set(a_reqs) | set(b_reqs)):
        spec_a = a_reqs.get(req_key)
        spec_b = b_reqs.get(req_key)
        if spec_a != spec_b:
            entries.append(
                DiffEntry(
                    component="requirement",
                    name=":".join(req_key),
                    classification=DiffClassification.PROJECT_CRITICAL,
                    a_value=spec_a,
                    b_value=spec_b,
                    detail="Declared project requirements differ between the two snapshots.",
                    project_critical=True,
                )
            )

    # ---- containers / wsl / gpu ---------------------------------------------------------
    if (a.containers is None) != (b.containers is None) or (
        a.containers
        and b.containers
        and a.containers.docker_daemon_ok != b.containers.docker_daemon_ok
    ):
        entries.append(
            DiffEntry(
                component="container",
                name="docker-daemon",
                classification=DiffClassification.PROJECT_CRITICAL,
                a_value=str(a.containers.docker_daemon_ok if a.containers else None),
                b_value=str(b.containers.docker_daemon_ok if b.containers else None),
                detail="Docker daemon health differs; container builds will behave differently.",
                project_critical=True,
            )
        )

    # Daemon health was the only container fact a diff could report, which made
    # "Docker works there but not here" answerable only when one side was
    # actually down. The engine's identity and configuration are what differ
    # when both are up and the build still behaves differently.
    if a.containers and b.containers:
        for name, a_raw, b_raw, detail, critical in _CONTAINER_AXES:
            va = getattr(a.containers, a_raw)
            vb = getattr(b.containers, b_raw)
            if va == vb or (va is None and vb is None):
                continue
            entries.append(
                DiffEntry(
                    component="container",
                    name=name,
                    classification=(
                        DiffClassification.PROJECT_CRITICAL
                        if critical
                        else DiffClassification.VERSION_DRIFT
                    ),
                    a_value=str(va) if va is not None else None,
                    b_value=str(vb) if vb is not None else None,
                    detail=detail,
                    project_critical=critical,
                )
            )

    # Docker CLI version drift is not build-breaking on its own, but it is the
    # first thing anyone asks about when an image builds on one machine only.
    _compare_optional(
        entries,
        component="container",
        name="docker-cli",
        a_value=a.containers.docker_cli_version if a.containers else None,
        b_value=b.containers.docker_cli_version if b.containers else None,
        classification=DiffClassification.VERSION_DRIFT,
        detail="Docker CLI version differs between the two machines.",
    )

    for name, attr, detail in (
        (
            "wsl-available",
            "available",
            "WSL availability differs; Linux-path builds behave differently.",
        ),
        (
            "wsl-default-distro",
            "default_distro",
            "The default WSL distro differs; commands run against another filesystem.",
        ),
    ):
        _compare_optional(
            entries,
            component="wsl",
            name=name,
            a_value=getattr(a.wsl, attr, None) if a.wsl else None,
            b_value=getattr(b.wsl, attr, None) if b.wsl else None,
            classification=DiffClassification.PLATFORM_EXPECTED,
            detail=detail,
        )

    # A CUDA/driver difference is the single most common reason an ML build or
    # test suite passes on one machine and fails on another.
    for name, attr in (
        ("nvidia-driver", "nvidia_driver"),
        ("cuda-toolkit", "cuda_toolkit"),
        ("rocm", "rocm"),
    ):
        _compare_optional(
            entries,
            component="gpu",
            name=name,
            a_value=getattr(a.gpu, attr, None) if a.gpu else None,
            b_value=getattr(b.gpu, attr, None) if b.gpu else None,
            classification=DiffClassification.PROJECT_CRITICAL,
            detail=f"{name} differs; GPU workloads may not reproduce.",
            project_critical=True,
        )

    return EnvironmentDiff(
        a_snapshot_id=a.snapshot_id,
        b_snapshot_id=b.snapshot_id,
        entries=tuple(entries),
    )
