"""The CUDA triple, and why "GPU not found" is the least useful answer.

Nothing about a broken CUDA setup is discovered by checking whether a GPU
exists. The GPU exists. What fails is a *relationship* between three versions:

    driver  ->  the highest CUDA runtime it can run
    toolkit ->  what `nvcc` compiles against
    wheel   ->  what the framework binary was built for

Any two of those can be right while the pair is wrong, and the error the user
actually sees says none of it. `CUDA driver version is insufficient for CUDA
runtime version` names neither version. `no kernel image is available for
execution on the device` is a compute-capability mismatch and does not contain
the words "compute capability". People reinstall the driver, which is usually
the one part that was fine.

**The driver's ceiling is not guessed from a table.** `nvidia-smi` prints it --
"CUDA Version: 12.4" in the header is the maximum runtime this driver supports,
not the toolkit that is installed. A hard-coded driver-to-CUDA table would be
wrong within a release and unfixable offline; the machine already knows the
answer and this reads it. The existing probe collected that number into a note
and threw it away.

Multiple GPUs get enumerated because a mixed pair is a real and confusing
failure: a build that targets the compute capability of device 0 produces
kernels the other card cannot run, and the error arrives at runtime on whichever
device the scheduler picked.

**What is deliberately not here:** which CUDA a framework wheel was built for.
Finding out means importing torch or jax, which takes seconds, allocates, and
occasionally initialises a context on a device somebody else is using. A
diagnostic that can disturb a running training job is not read-only in any sense
that matters. The remediation hint names the one-line command instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "CudaVerdict",
    "GpuDevice",
    "NvidiaState",
    "compare_toolkit_to_driver",
    "mixed_architectures",
    "parse_query_gpu",
    "parse_smi_header",
]


@dataclass(frozen=True)
class GpuDevice:
    """One physical device, as `nvidia-smi` reports it."""

    index: int
    name: str
    memory_mib: int | None = None
    #: The `sm_XX` architecture, as a dotted string ("8.6"). None when the
    #: installed `nvidia-smi` is too old for `--query-gpu=compute_cap`, which
    #: is common enough that it must not be reported as a device with none.
    compute_capability: str | None = None


@dataclass(frozen=True)
class NvidiaState:
    """What the driver says about itself and its devices."""

    driver: str | None = None
    #: The highest CUDA *runtime* this driver can run, printed by nvidia-smi.
    #: Not the installed toolkit, and the two are constantly confused.
    max_cuda: str | None = None
    devices: tuple[GpuDevice, ...] = ()

    @property
    def present(self) -> bool:
        return self.driver is not None


_DRIVER = re.compile(r"Driver Version:\s*([\d.]+)")
_MAX_CUDA = re.compile(r"CUDA Version:\s*([\d.]+)")


def parse_smi_header(text: str) -> NvidiaState:
    """Read the banner of a bare `nvidia-smi`.

    The fallback path. `--query-gpu` gives structured output and is not present
    on every driver old enough to still be in service, and a parser that only
    handles the good case reports "no GPU" on the machines most likely to have
    a version problem.
    """
    driver = _DRIVER.search(text or "")
    max_cuda = _MAX_CUDA.search(text or "")
    return NvidiaState(
        driver=driver.group(1) if driver else None,
        max_cuda=max_cuda.group(1) if max_cuda else None,
    )


def parse_query_gpu(text: str) -> tuple[GpuDevice, ...]:
    """Read `nvidia-smi --query-gpu=index,name,memory.total,compute_cap --format=csv,noheader`.

    Fields that come back as `[N/A]` or `[Not Supported]` become `None` rather
    than the literal string. A device listed with a compute capability of
    "[Not Supported]" would otherwise compare unequal to every other device and
    manufacture a mixed-architecture warning out of an old driver.
    """
    devices: list[GpuDevice] = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        memory = None
        if len(parts) > 2:
            match = re.match(r"(\d+)", parts[2])
            memory = int(match.group(1)) if match else None
        capability = parts[3] if len(parts) > 3 else ""
        devices.append(
            GpuDevice(
                index=int(parts[0]),
                name=parts[1],
                memory_mib=memory,
                compute_capability=(capability if re.fullmatch(r"\d+\.\d+", capability) else None),
            )
        )
    return tuple(devices)


@dataclass(frozen=True)
class CudaVerdict:
    """Whether the installed toolkit can actually run on this driver."""

    ok: bool | None
    summary: str
    detected: str | None = None
    required: str | None = None
    #: Set when the answer could not be determined, saying which half was
    #: missing. "Unknown" and "fine" must not render the same way.
    unknown_because: str | None = None


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", value)[:3])


def compare_toolkit_to_driver(toolkit: str | None, max_cuda: str | None) -> CudaVerdict:
    """Compare the installed CUDA toolkit with the driver's runtime ceiling.

    Major version first, because that is what CUDA's own compatibility promise
    is written in: since 11.0, any 11.x runtime works on a driver that meets the
    11.0 minimum, and any 12.x on one that meets 12.0. So a toolkit of 12.4 on a
    driver reporting 12.2 is **fine** -- minor-version compatibility covers it --
    while a toolkit of 12.0 on a driver reporting 11.8 is not, and no amount of
    patch-level comparison distinguishes those two cases.

    Getting this backwards is the common failure of hand-rolled checks: a strict
    `toolkit <= max_cuda` reports a working machine as broken, which is worse
    than saying nothing, because somebody then upgrades a driver that was fine.
    """
    if not toolkit and not max_cuda:
        return CudaVerdict(
            ok=None,
            summary="No CUDA toolkit and no NVIDIA driver detected.",
            unknown_because="neither nvcc nor nvidia-smi answered",
        )
    if not max_cuda:
        return CudaVerdict(
            ok=None,
            summary=f"CUDA toolkit {toolkit} is installed; no NVIDIA driver answered.",
            detected=toolkit,
            unknown_because="nvidia-smi did not report a driver",
        )
    if not toolkit:
        return CudaVerdict(
            ok=None,
            summary=(
                f"Driver supports CUDA runtimes up to {max_cuda}; no nvcc on PATH, so "
                "the installed toolkit is unknown."
            ),
            required=f"<={max_cuda}",
            unknown_because="nvcc is not on PATH",
        )

    toolkit_parts = _version_tuple(toolkit)
    driver_parts = _version_tuple(max_cuda)
    if not toolkit_parts or not driver_parts:
        return CudaVerdict(
            ok=None,
            summary=f"Could not compare CUDA toolkit {toolkit} with driver ceiling {max_cuda}.",
            detected=toolkit,
            required=f"<={max_cuda}",
            unknown_because="a version string did not parse",
        )

    if toolkit_parts[0] > driver_parts[0]:
        return CudaVerdict(
            ok=False,
            summary=(
                f"CUDA toolkit {toolkit} needs a newer driver: this one supports CUDA "
                f"runtimes up to {max_cuda}. Anything built with nvcc will fail at "
                "launch with 'CUDA driver version is insufficient for CUDA runtime "
                "version', which names neither number."
            ),
            detected=toolkit,
            required=f"a driver supporting CUDA {toolkit_parts[0]}.x",
        )

    return CudaVerdict(
        ok=True,
        summary=(
            f"CUDA toolkit {toolkit} runs on this driver, which supports up to {max_cuda}."
            + (
                " Minor-version compatibility covers the gap."
                if toolkit_parts > driver_parts
                else ""
            )
        ),
        detected=toolkit,
        required=f"<={driver_parts[0]}.x",
    )


def mixed_architectures(capabilities: Iterable[str | None]) -> tuple[str, ...]:
    """Distinct compute capabilities across the installed devices.

    More than one is the answer to "why does it work on device 0 and crash on
    device 1". A build targeting one architecture produces kernels the other
    card cannot execute, and the failure -- `no kernel image is available for
    execution on the device` -- names neither the device nor the architecture.

    Takes capabilities rather than devices so the probe can pass its own model
    objects through without a converter whose only job is to change the type.

    Unknown capabilities are skipped rather than treated as a distinct value:
    an `nvidia-smi` too old for `--query-gpu=compute_cap` would otherwise
    manufacture this warning on a perfectly uniform machine.
    """
    known = {c for c in capabilities if c}
    return tuple(sorted(known)) if len(known) > 1 else ()
