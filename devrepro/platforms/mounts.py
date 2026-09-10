"""Which filesystem the project sits on, and why that is the whole answer.

"The build is slow on my machine" has one cause that dwarfs every other, and
nothing reports it: the source tree is on a filesystem that costs a millisecond
per file operation instead of a microsecond. A `node_modules` install touches
hundreds of thousands of files. Three orders of magnitude on each of those is
the difference between twenty seconds and twenty minutes, and no profiler
anybody runs will point at it, because nothing is *wrong* -- every operation
succeeds.

Three shapes account for almost all of it:

- **A WSL2 shell working under `/mnt/c`.** Every read crosses a 9p protocol
  boundary into the Windows filesystem. This is the single most common
  performance complaint about WSL and the fix -- move the tree into the Linux
  filesystem -- takes one `cp`.
- **A network mount.** SMB or NFS, or a Windows mapped drive. Latency per
  operation, plus a lock protocol that some build tools handle badly.
- **A Windows path bind-mounted into a Linux container.** Same crossing as the
  first, in the other direction, and it is invisible from inside the container
  where the slowness is felt.

**This classifies; it does not measure.** A benchmark would need to write
files, and this project is read-only. It would also produce a number nobody can
act on, whereas "your tree is on `/mnt/c`" names both the cause and the fix. The
classification comes from the path and from mount metadata already in
`/proc/mounts` or `mount` output -- no I/O against the volume itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "SLOW_FILESYSTEMS",
    "MountKind",
    "MountVerdict",
    "classify_path",
    "parse_proc_mounts",
]

#: Filesystem types where per-operation latency is the dominant cost. `9p` and
#: `drvfs` are the WSL crossings; the rest are networked.
SLOW_FILESYSTEMS: frozenset[str] = frozenset(
    {"9p", "drvfs", "cifs", "smbfs", "smb3", "nfs", "nfs4", "afpfs", "fuse.sshfs", "virtiofs"}
)

MountKind = str


@dataclass(frozen=True)
class MountVerdict:
    """What kind of storage a path is on, and what it costs."""

    kind: MountKind
    #: `True` when per-operation latency is high enough to dominate a build.
    #: `None` when the mount could not be identified -- which is not the same
    #: as fast, and is reported as unknown rather than as a pass.
    slow: bool | None
    detail: str
    remedy: str | None = None


_MOUNT_LINE = re.compile(r"^\S+\s+(?P<point>\S+)\s+(?P<fstype>\S+)\s")


def parse_proc_mounts(text: str) -> tuple[tuple[str, str], ...]:
    r"""`(mount point, filesystem type)` pairs from `/proc/mounts` or `mount -v`.

    Octal escapes in mount points are decoded: a path containing a space is
    written `\\040` in `/proc/mounts`, and comparing the raw form against a real
    path never matches. Rare, and silently wrong when it happens.
    """
    pairs: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        match = _MOUNT_LINE.match(line)
        if not match:
            continue
        point = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), match.group("point"))
        pairs.append((point, match.group("fstype")))
    # Longest mount point first, so `/mnt/c/work` wins over `/`.
    return tuple(sorted(pairs, key=lambda pair: len(pair[0]), reverse=True))


def _windows_verdict(path: str) -> MountVerdict | None:
    if path.startswith("\\\\") or path.startswith("//"):
        return MountVerdict(
            kind="network-share",
            slow=True,
            detail=(
                "The project is on a UNC network path. Every file operation is a "
                "round trip, and a dependency install performs hundreds of thousands "
                "of them."
            ),
            remedy="Work from a local disk and sync deliberately, rather than building over SMB.",
        )
    return None


def classify_path(
    path: str,
    *,
    platform: str,
    is_wsl: bool = False,
    mounts: tuple[tuple[str, str], ...] = (),
) -> MountVerdict:
    """What kind of filesystem `path` lives on.

    Takes mount metadata rather than reading it, so the interesting cases can
    be tested from a machine that has none of them.
    """
    normalised = path.replace("\\", "/")

    if platform == "windows":
        verdict = _windows_verdict(path)
        if verdict:
            return verdict
        return MountVerdict(
            kind="local",
            slow=False,
            detail="The project is on a local Windows volume.",
        )

    if is_wsl and re.match(r"^/mnt/[a-z]/", normalised):
        drive = normalised[5]
        return MountVerdict(
            kind="wsl-windows-crossing",
            slow=True,
            detail=(
                f"The project is under /mnt/{drive}, so every file operation crosses "
                "from the Linux filesystem into the Windows one over 9p. For a tree "
                "with many small files this is the dominant cost of the build, and "
                "nothing else about the machine will look wrong."
            ),
            remedy=(
                "Move the tree into the Linux filesystem -- somewhere under ~ -- and "
                "open it from VS Code with the WSL extension, which keeps the editor "
                "on the Windows side and the files on the Linux side."
            ),
        )

    for point, fstype in mounts:
        if normalised == point or normalised.startswith(point.rstrip("/") + "/"):
            if fstype in SLOW_FILESYSTEMS:
                return MountVerdict(
                    kind=f"network:{fstype}",
                    slow=True,
                    detail=(
                        f"The project is on a {fstype} mount at {point}. Per-operation "
                        "latency, not throughput, is what a build spends its time on."
                    ),
                    remedy=(
                        "Build from a local disk. If the tree must live on the share, "
                        "keep the dependency directory local -- most package managers "
                        "accept a cache or store path outside the project."
                    ),
                )
            return MountVerdict(
                kind=f"local:{fstype}",
                slow=False,
                detail=f"The project is on a local {fstype} filesystem.",
            )

    return MountVerdict(
        kind="unknown",
        slow=None,
        detail="Could not determine what filesystem the project is on.",
    )
