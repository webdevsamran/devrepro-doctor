"""What is actually behind the `docker` command, and what shape it is in.

The container probe answered one question -- is a daemon responding -- and that
is the least interesting half. "Docker works there but not here" is one of the
problems this project opens by promising to answer, and the causes are almost
never "the daemon is down", because that one is obvious the moment you try. The
causes that waste an afternoon are:

* **A different engine is behind the same CLI.** Docker Desktop, Colima,
  Rancher Desktop, OrbStack, Podman's machine and a plain Linux daemon all
  answer `docker`. They differ on file-sharing performance, on which host paths
  bind-mount at all, and on whether the VM has enough memory for the build.
* **The daemon runs a different architecture.** An arm64 host emulating amd64
  builds correctly and roughly ten times slower, and nothing in the output says
  so.
* **cgroup v1.** Memory limits behave differently, and a container that gets
  OOM-killed in CI passes locally.
* **A legacy storage driver.** `vfs` copies the entire filesystem per layer;
  `devicemapper` and `aufs` are removed in current engines.
* **The disk is full of things nobody needs.** Reclaimable space is a fact the
  daemon already computes, and a build that fails on "no space left on device"
  usually has tens of gigabytes of dangling layers behind it.

Every parser here takes text the caller already fetched. Nothing in this module
runs a command, so each one is testable against a recorded `docker info` from a
machine none of us has.

**One deliberate omission:** the daemon endpoint is classified, never stored. A
Colima socket path is `unix:///Users/<name>/.colima/default/docker.sock`, so
keeping the endpoint would put a username into every snapshot for the sake of a
string nobody reads. The *kind* of endpoint and the *backend* it implies are
the useful parts, and they carry no identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__all__ = [
    "LEGACY_STORAGE_DRIVERS",
    "RUNTIME_CLIS",
    "ContainerEngineInfo",
    "DiskUsage",
    "classify_endpoint",
    "identify_backend",
    "parse_docker_info",
    "parse_system_df",
]

#: Storage drivers that are removed, deprecated, or pathologically slow.
#: `vfs` is the one that surprises people: it is correct, it is the fallback
#: when nothing else is available, and it copies the whole filesystem for every
#: layer, so a build that takes a minute elsewhere takes twenty.
LEGACY_STORAGE_DRIVERS: dict[str, str] = {
    "aufs": "removed in Docker 24; the daemon will refuse to start on newer versions",
    "devicemapper": "removed in Docker 25; migrate to overlay2",
    "vfs": "no copy-on-write at all -- every layer is a full copy of the one below",
    "btrfs": "supported, but needs the host filesystem to be btrfs and is rarely intended",
    "overlay": "superseded by overlay2; kernels since 4.0 should use overlay2",
}

#: CLIs that indicate an alternative engine is installed, whether or not it is
#: the one currently answering `docker`.
RUNTIME_CLIS: dict[str, str] = {
    "colima": "Colima",
    "rdctl": "Rancher Desktop",
    "orb": "OrbStack",
    "limactl": "Lima",
    "podman": "Podman",
    "nerdctl": "nerdctl / containerd",
    "minikube": "minikube",
}


@dataclass(frozen=True)
class ContainerEngineInfo:
    """The parts of `docker info` that change whether a build works."""

    server_version: str | None = None
    server_os: str | None = None
    server_arch: str | None = None
    storage_driver: str | None = None
    cgroup_version: str | None = None
    cgroup_driver: str | None = None
    cpus: int | None = None
    memory_bytes: int | None = None
    rootless: bool | None = None
    #: The daemon's own name for itself, e.g. `desktop-linux`, `default`.
    #: Present in `docker info` as `Name` and useful for backend detection.
    name: str | None = None
    live_containers: int | None = None
    images: int | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiskUsage:
    """What `docker system df` says is on disk and what is reclaimable."""

    images_bytes: int | None = None
    containers_bytes: int | None = None
    volumes_bytes: int | None = None
    build_cache_bytes: int | None = None
    reclaimable_bytes: int | None = None
    dangling_images: int | None = None
    unused_volumes: int | None = None

    @property
    def total_bytes(self) -> int:
        return sum(
            value or 0
            for value in (
                self.images_bytes,
                self.containers_bytes,
                self.volumes_bytes,
                self.build_cache_bytes,
            )
        )


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_docker_info(text: str) -> ContainerEngineInfo | None:
    """Parse `docker info --format {{json .}}`, or None if it is not that.

    Returns None rather than raising for anything unparseable. A daemon that is
    starting up prints a partial object, an old daemon prints a different one,
    and neither is a reason for a diagnostic tool to fall over.
    """
    try:
        data: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    # `CgroupVersion` is a string in the JSON ("1"/"2") and absent entirely on
    # Windows containers and on macOS, where cgroups are the VM's business.
    warnings = data.get("Warnings")
    return ContainerEngineInfo(
        server_version=_as_str(data.get("ServerVersion")),
        server_os=_as_str(data.get("OSType")),
        server_arch=_as_str(data.get("Architecture")),
        storage_driver=_as_str(data.get("Driver")),
        cgroup_version=_as_str(data.get("CgroupVersion")),
        cgroup_driver=_as_str(data.get("CgroupDriver")),
        cpus=_as_int(data.get("NCPU")),
        memory_bytes=_as_int(data.get("MemTotal")),
        rootless=_rootless(data),
        name=_as_str(data.get("Name")),
        live_containers=_as_int(data.get("ContainersRunning")),
        images=_as_int(data.get("Images")),
        warnings=(
            tuple(w for w in warnings if isinstance(w, str)) if isinstance(warnings, list) else ()
        ),
    )


def _rootless(data: dict[str, Any]) -> bool | None:
    """Rootless mode is reported in `SecurityOptions`, not as its own key."""
    options = data.get("SecurityOptions")
    if not isinstance(options, list):
        return None
    return any(isinstance(o, str) and "rootless" in o for o in options)


def parse_system_df(text: str) -> DiskUsage | None:
    """Parse `docker system df --format {{json .}}`.

    Docker emits this as one JSON object *per line*, not as an array -- the
    same newline-delimited shape as `docker ps --format json`. Feeding the
    whole output to `json.loads` fails on the second line, which is why this
    reads it line by line.

    Sizes arrive as human strings ("1.2GB", "983.4MB"), so they are parsed back
    into bytes rather than compared as text.
    """
    images = containers = volumes = cache = None
    reclaimable = 0
    dangling = unused = None
    seen = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        seen = True

        kind = _as_str(row.get("Type")) or ""
        size = _parse_size(_as_str(row.get("Size")))
        recl = _parse_size(_strip_percent(_as_str(row.get("Reclaimable"))))
        if recl is not None:
            reclaimable += recl

        active = _as_int(row.get("Active"))
        total = _as_int(row.get("TotalCount"))

        if kind == "Images":
            images = size
            if total is not None and active is not None:
                dangling = max(total - active, 0)
        elif kind == "Containers":
            containers = size
        elif kind == "Local Volumes":
            volumes = size
            if total is not None and active is not None:
                unused = max(total - active, 0)
        elif kind == "Build Cache":
            cache = size

    if not seen:
        return None
    return DiskUsage(
        images_bytes=images,
        containers_bytes=containers,
        volumes_bytes=volumes,
        build_cache_bytes=cache,
        reclaimable_bytes=reclaimable,
        dangling_images=dangling,
        unused_volumes=unused,
    )


def _strip_percent(text: str | None) -> str | None:
    """`Reclaimable` is rendered as "1.2GB (85%)"; the percentage is noise."""
    if text is None:
        return None
    return text.split("(")[0].strip()


_UNITS: dict[str, int] = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def _parse_size(text: str | None) -> int | None:
    """Turn "1.234GB" into bytes.

    Docker uses decimal units in this output (GB, not GiB), so this does too --
    reporting 1.2GB as 1.29e9 because we assumed binary would make the number
    disagree with what `docker system df` prints beside it.
    """
    if not text:
        return None
    cleaned = text.strip().replace(" ", "").lower()
    for suffix in sorted(_UNITS, key=len, reverse=True):
        if cleaned.endswith(suffix):
            number = cleaned[: -len(suffix)]
            try:
                return int(float(number) * _UNITS[suffix])
            except ValueError:
                return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def classify_endpoint(endpoint: str | None) -> str | None:
    """The *kind* of a daemon endpoint, never the endpoint itself.

    A Colima socket is `unix:///Users/<name>/.colima/...`, so storing the
    endpoint would put a username into every snapshot. The scheme is the part
    that carries diagnostic weight -- an `ssh://` endpoint means builds run on
    another machine entirely, which explains a great deal on its own.
    """
    if not endpoint:
        return None
    scheme, _, _ = endpoint.partition("://")
    scheme = scheme.strip().lower()
    return scheme if scheme in {"unix", "npipe", "tcp", "ssh", "fd"} else "other"


def identify_backend(
    *,
    endpoint: str | None = None,
    context_name: str | None = None,
    daemon_name: str | None = None,
    platform: str = "linux",
) -> str | None:
    """Which engine is behind `docker`, from the strings that name it.

    Matched on the endpoint path, the context name and the daemon's own `Name`,
    in that order of reliability. The endpoint is read here and discarded by the
    caller -- identifying the backend is exactly the use that justifies looking
    at it at all.

    Returns None when nothing identifies it, which is the honest answer for a
    plain daemon on a host that is not any of these.
    """
    haystacks = [h.lower() for h in (endpoint, context_name, daemon_name) if h]
    blob = " ".join(haystacks)

    # Ordered: the more specific marker wins. `rancher-desktop` contains
    # "desktop", so Docker Desktop cannot be tested first.
    for marker, backend in (
        (".colima", "colima"),
        ("colima", "colima"),
        ("rancher-desktop", "rancher-desktop"),
        ("rd.sock", "rancher-desktop"),
        (".rd/", "rancher-desktop"),
        ("orbstack", "orbstack"),
        (".orbstack", "orbstack"),
        ("dockerdesktop", "docker-desktop"),
        ("docker-desktop", "docker-desktop"),
        ("desktop-linux", "docker-desktop"),
        ("desktop-windows", "docker-desktop"),
        ("podman", "podman"),
        (".lima", "lima"),
        ("lima", "lima"),
        ("minikube", "minikube"),
    ):
        if marker in blob:
            return backend

    if not blob:
        return None
    # A bare unix socket at the conventional path on Linux is the native daemon.
    if "/var/run/docker.sock" in blob or "/run/docker.sock" in blob:
        return "native" if platform == "linux" else "docker-desktop"
    return None
