"""Whether the sandbox an agent runs in resembles the machine it was tested on.

The toolchain half of this question already ships as `devrepro ci-diff`. What
is left is the half nobody checks, because it produces no version mismatch and
no missing binary -- the *shape* of the box:

**Memory.** Docker Desktop ships with a memory ceiling far below the host's,
and a build that links comfortably in 32 GB is killed at 2 GB with exit code
137 and no message. `137` is `128 + 9`: SIGKILL, from the kernel's OOM killer,
which does not write to the build log. The usual diagnosis is "the compiler
crashed", and the usual fix attempted is a compiler flag.

**CPU count.** Build tools read the *host's* core count through interfaces that
predate cgroups -- `nproc`, `os.cpu_count()`, `Runtime.availableProcessors()` on
older JVMs -- and spawn that many workers inside a container allowed two. The
result is thrash, not an error: the build finishes, three times slower, and
nothing anywhere says why.

**Network policy.** A sandbox with no network is the correct default for an
agent and the wrong one for a build whose first step is a dependency install.
Declaring both, in the same repository, is common and neither declaration knows
about the other.

Everything here reads declarations and engine metadata that a scan already
collected. Nothing is started, and no container is run to find out.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "OOM_EXIT_CODE",
    "TIGHT_MEMORY_RATIO",
    "ParityFinding",
    "SandboxLimits",
    "compare_limits",
    "parse_compose_limits",
    "parse_devcontainer_limits",
    "parse_memory_value",
]

#: `128 + SIGKILL`. Worth naming in the output, because it is the only trace the
#: OOM killer leaves and nobody recognises it.
OOM_EXIT_CODE = 137

#: A sandbox with less than this share of host memory is worth reporting. Not a
#: rule -- plenty of containers are deliberately small -- but below a quarter
#: the difference stops being a configuration choice and starts being the
#: reason a build behaves differently.
TIGHT_MEMORY_RATIO = 0.25

_UNITS = {"b": 1, "k": 1000, "m": 1000**2, "g": 1000**3, "t": 1000**4}
_BINARY_UNITS = {"kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}

_MEMORY = re.compile(r"^\s*(?P<number>[\d.]+)\s*(?P<unit>[a-zA-Z]*)\s*$")


def parse_memory_value(raw: str | int | None) -> int | None:
    """Read a memory limit the way the tool that wrote it meant it.

    Compose and Docker disagree with themselves here and it matters: `2g` in a
    `mem_limit` is 2 * 1000^3, and `2gb` is 2 * 1024^3. A parser that treats
    them the same is off by 7% -- which is enough to put a limit either side of
    a threshold, and never enough for anybody to notice the parser was wrong.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw

    match = _MEMORY.match(str(raw))
    if not match:
        return None
    try:
        number = float(match.group("number"))
    except ValueError:  # pragma: no cover - the pattern guarantees digits
        return None

    unit = match.group("unit").lower()
    if not unit:
        return int(number)
    if unit in _BINARY_UNITS:
        return int(number * _BINARY_UNITS[unit])
    if unit in _UNITS:
        return int(number * _UNITS[unit])
    return None


@dataclass(frozen=True)
class SandboxLimits:
    """What a sandbox declaration says the box will be."""

    source: str
    memory_bytes: int | None = None
    cpus: float | None = None
    #: `True` when the declaration explicitly turns the network off.
    network_disabled: bool | None = None

    @property
    def declares_anything(self) -> bool:
        return (
            self.memory_bytes is not None
            or self.cpus is not None
            or self.network_disabled is not None
        )


_COMPOSE_MEM = re.compile(r"^\s*mem_limit:\s*[\"']?([\w.]+)", re.MULTILINE)
_COMPOSE_LIMIT_MEM = re.compile(r"^\s{6,}memory:\s*[\"']?([\w.]+)", re.MULTILINE)
_COMPOSE_CPUS = re.compile(r"^\s*(?:cpus|cpu_count):\s*[\"']?([\d.]+)", re.MULTILINE)
_COMPOSE_NET_NONE = re.compile(r"^\s*network_mode:\s*[\"']?none", re.MULTILINE)


def parse_compose_limits(text: str, *, source: str = "docker-compose.yml") -> SandboxLimits:
    """Resource limits declared in a compose file.

    Read with regexes rather than a YAML parser, for the same reason the CI
    workflow reader is: this project has no YAML dependency, and the fields
    that matter are flat scalars. A file too exotic for this produces no limits,
    which reports as "not declared" rather than as a wrong number.

    Both spellings are handled. `mem_limit` is the version 2 form and
    `deploy.resources.limits.memory` is the version 3 form, and a great many
    real compose files carry one of each because they were migrated halfway.
    """
    memory = _COMPOSE_MEM.search(text or "") or _COMPOSE_LIMIT_MEM.search(text or "")
    cpus = _COMPOSE_CPUS.search(text or "")
    return SandboxLimits(
        source=source,
        memory_bytes=parse_memory_value(memory.group(1)) if memory else None,
        cpus=float(cpus.group(1)) if cpus else None,
        network_disabled=True if _COMPOSE_NET_NONE.search(text or "") else None,
    )


_RUNARG_MEMORY = re.compile(r"--memory(?:=|\s+)([\w.]+)")
_RUNARG_CPUS = re.compile(r"--cpus(?:=|\s+)([\d.]+)")


def parse_devcontainer_limits(text: str) -> SandboxLimits:
    """Resource limits declared in a devcontainer's `runArgs`.

    `devcontainer.json` is JSON with comments, which `json` refuses. Line
    comments are stripped and it is retried once; anything still unreadable
    yields no limits rather than a guess.
    """
    # Unannotated: `json.loads` returns `Any`, and declaring it a dict here
    # would make the isinstance guard below unreachable to the type checker --
    # while doing nothing at all about a file whose top level is a list.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        stripped = re.sub(r"^\s*//.*$", "", text or "", flags=re.MULTILINE)
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return SandboxLimits(source=".devcontainer/devcontainer.json")
    if not isinstance(payload, dict):
        return SandboxLimits(source=".devcontainer/devcontainer.json")

    args = payload.get("runArgs")
    joined = " ".join(str(a) for a in args) if isinstance(args, list) else ""
    memory = _RUNARG_MEMORY.search(joined)
    cpus = _RUNARG_CPUS.search(joined)
    return SandboxLimits(
        source=".devcontainer/devcontainer.json",
        memory_bytes=parse_memory_value(memory.group(1)) if memory else None,
        cpus=float(cpus.group(1)) if cpus else None,
        network_disabled=True if "--network=none" in joined or "--network none" in joined else None,
    )


def read_declared_limits(root: Path) -> tuple[SandboxLimits, ...]:
    """Every sandbox declaration in this repository."""
    found: list[SandboxLimits] = []
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        path = root / name
        if path.is_file():
            with suppress(OSError):  # an unreadable file declares nothing
                found.append(parse_compose_limits(path.read_text(encoding="utf-8"), source=name))
            break

    devcontainer = root / ".devcontainer" / "devcontainer.json"
    if not devcontainer.is_file():
        devcontainer = root / ".devcontainer.json"
    if devcontainer.is_file():
        with suppress(OSError):  # an unreadable file declares nothing
            found.append(parse_devcontainer_limits(devcontainer.read_text(encoding="utf-8")))

    return tuple(f for f in found if f.declares_anything)


@dataclass(frozen=True)
class ParityFinding:
    """One way the sandbox does not resemble the host."""

    kind: str
    summary: str
    detail: str
    remedy: str | None = None


def compare_limits(
    *,
    host_memory_bytes: int | None,
    host_cpus: int | None,
    engine_memory_bytes: int | None = None,
    engine_cpus: int | None = None,
    declared: tuple[SandboxLimits, ...] = (),
    needs_network: bool = False,
) -> tuple[ParityFinding, ...]:
    """Every way the box an agent gets differs from the machine it was tested on.

    Silent when the numbers are unknown. A missing host memory figure is not
    evidence that the sandbox is small, and this is the kind of check that would
    otherwise fire on every machine whose `/proc/meminfo` could not be read.
    """
    findings: list[ParityFinding] = []

    effective_memory = engine_memory_bytes
    effective_cpus: float | None = float(engine_cpus) if engine_cpus else None
    for limit in declared:
        if limit.memory_bytes is not None:
            effective_memory = (
                min(effective_memory, limit.memory_bytes)
                if effective_memory
                else limit.memory_bytes
            )
        if limit.cpus is not None:
            effective_cpus = min(effective_cpus, limit.cpus) if effective_cpus else limit.cpus

    if host_memory_bytes and effective_memory:
        ratio = effective_memory / host_memory_bytes
        if ratio < TIGHT_MEMORY_RATIO:
            findings.append(
                ParityFinding(
                    kind="memory",
                    summary=(
                        f"The sandbox gets {effective_memory / 1024**3:.1f} GiB of the "
                        f"host's {host_memory_bytes / 1024**3:.1f} GiB "
                        f"({ratio:.0%})."
                    ),
                    detail=(
                        "A build that links comfortably on this machine can be killed "
                        f"in the sandbox with exit code {OOM_EXIT_CODE} -- "
                        f"{OOM_EXIT_CODE} is 128 plus SIGKILL, sent by the kernel's OOM "
                        "killer, which writes nothing to the build log. It reads as a "
                        "compiler crash."
                    ),
                    remedy=(
                        "Raise the engine's memory limit (Docker Desktop: Settings > "
                        "Resources), or lower the build's parallelism so the peak fits."
                    ),
                )
            )

    if host_cpus and effective_cpus and effective_cpus < host_cpus:
        findings.append(
            ParityFinding(
                kind="cpu",
                summary=(f"The sandbox gets {effective_cpus:g} of the host's {host_cpus} cores."),
                detail=(
                    "Build tools that read the core count through `nproc`, "
                    "`os.cpu_count()` or an older JVM see the host's number, not the "
                    "sandbox's, and spawn that many workers into a smaller box. The "
                    "build does not fail -- it thrashes, and finishes several times "
                    "slower with nothing in any log to say why."
                ),
                remedy=(
                    "Pin the parallelism explicitly (`make -j`, `cargo build -j`, "
                    "`CARGO_BUILD_JOBS`, `MAKEFLAGS`) rather than letting the tool "
                    "detect it."
                ),
            )
        )

    disabled = [limit for limit in declared if limit.network_disabled]
    if disabled and needs_network:
        findings.append(
            ParityFinding(
                kind="network",
                summary=(
                    f"{disabled[0].source} disables the network, and this project's "
                    "setup fetches dependencies."
                ),
                detail=(
                    "No network is the right default for an agent sandbox and the "
                    "wrong one for a first build. Both declarations are in this "
                    "repository and neither knows about the other."
                ),
                remedy=(
                    "Warm the dependency cache in an image layer, or vendor the "
                    "dependencies, so the isolated run needs nothing from outside."
                ),
            )
        )

    return tuple(findings)
