"""ABI compatibility: can a prebuilt binary load on this machine?

Package managers pick which compiled artefact to download from three facts --
architecture, C library, and that library's version -- and every way of getting
one wrong produces a failure about something else. A `manylinux` wheel on Alpine
does not load, so pip falls back to building from source and the error names a
missing header. An x86_64 interpreter on an arm64 host downloads x86_64 wheels
for ever, succeeds every time, and runs everything under translation.

Read from what the machine already reports. Parsing lives in
`devrepro.platforms.abi` so a musl host and an arm64 Mac can both be tested
from a machine that is neither.
"""

from __future__ import annotations

import platform

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.platforms.abi import (
    COMMON_MANYLINUX,
    MANYLINUX_GLIBC,
    AbiFacts,
    compare_arch,
    normalise_arch,
    parse_libc,
)
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["AbiProbe"]

#: Runtimes that will tell you their own architecture cheaply. The answer is
#: the runtime's, not the machine's, which is exactly the point.
_RUNTIME_ARCH_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("node", ("node", "-p", "process.arch")),
    ("go", ("go", "env", "GOARCH")),
)


class AbiProbe(Probe):
    id = "abi/compat"
    version = "1"

    def run(self) -> ProbeResult:
        facts = self._collect()
        findings: list[Finding] = []
        findings.extend(self._arch_findings(facts))
        findings.extend(self._libc_findings(facts))

        libc = facts.libc
        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={
                "host_arch": facts.host_arch,
                "interpreter_arch": facts.interpreter_arch,
                "translated": facts.translated,
                "libc_flavour": libc.flavour if libc else None,
                "libc_version": libc.version_text if libc else None,
                "supported_wheel_tags": list(facts.supported_wheel_tags),
                "runtime_arches": dict(facts.runtime_arches),
            },
        )

    def _collect(self) -> AbiFacts:
        runner = self.ctx.runner

        # `platform.machine()` reports what the *process* is told, which under
        # translation is the emulated architecture. `uname -m` reports the same
        # thing for the same reason, so neither alone can detect translation --
        # that is what the sysctl below is for.
        interpreter_arch = platform.machine() or None
        host_arch = self.ctx.platform_info.arch or interpreter_arch

        translated: bool | None = None
        if self.ctx.platform == "macos":
            result = runner.run(("sysctl", "-n", "sysctl.proc_translated"), timeout=10)
            if result.ok:
                answer = result.stdout.strip()
                translated = answer == "1" if answer in {"0", "1"} else None
            if translated:
                # Under Rosetta the process is x86_64 and the machine is arm64,
                # and nothing else in the environment says so.
                interpreter_arch = "x86_64"
                host_arch = "arm64"

        libc = None
        if self.ctx.platform == "linux":
            result = runner.run(("ldd", "--version"), timeout=10)
            # musl writes its banner to stderr and exits non-zero. Reading only
            # a successful stdout concludes there is no libc at all on exactly
            # the systems where the answer matters.
            libc = parse_libc(f"{result.stdout}\n{result.stderr}")

        runtimes: list[tuple[str, str]] = []
        for name, argv in _RUNTIME_ARCH_COMMANDS:
            result = runner.run(argv, timeout=10)
            if result.ok and result.stdout.strip():
                runtimes.append((name, result.stdout.strip()))

        return AbiFacts(
            host_arch=host_arch,
            interpreter_arch=interpreter_arch,
            translated=translated,
            libc=libc,
            runtime_arches=tuple(runtimes),
        )

    def _arch_findings(self, facts: AbiFacts) -> list[Finding]:
        out: list[Finding] = []
        evidence = (
            Evidence(
                source="system",
                excerpt=f"host={facts.host_arch} interpreter={facts.interpreter_arch}",
            ),
        )

        if facts.translated:
            out.append(
                self.finding(
                    "abi/translated-process",
                    FindingState.WARN,
                    "This process runs under Rosetta translation.",
                    evidence=(self.cmd_evidence(("sysctl", "-n", "sysctl.proc_translated"), "1"),),
                    detected="x86_64 under translation",
                    required="arm64 native",
                    component="abi",
                    remediation_hint="Every package this process installs will be the x86_64 "
                    "build, including native extensions, and they stay x86_64 for anything "
                    "else that uses them. Install an arm64 build of the runtime and re-create "
                    "the virtualenv; the machine will not tell you it is doing this.",
                )
            )
        elif facts.arch_matches is False:
            out.append(
                self.finding(
                    "abi/interpreter-arch-mismatch",
                    FindingState.WARN,
                    f"The interpreter reports {facts.interpreter_arch} on a "
                    f"{facts.host_arch} machine.",
                    evidence=evidence,
                    detected=facts.interpreter_arch,
                    required=facts.host_arch,
                    component="abi",
                    remediation_hint="Prebuilt packages are chosen by the interpreter's "
                    "architecture, not the machine's, so everything installed here is built "
                    "for the wrong one. Reinstall the runtime for this machine.",
                )
            )

        for name, reported in facts.runtime_arches:
            if compare_arch(reported, facts.host_arch) is False:
                out.append(
                    self.finding(
                        "abi/runtime-arch-mismatch",
                        FindingState.WARN,
                        f"{name} reports {reported} on a {facts.host_arch} machine.",
                        evidence=(
                            Evidence(
                                source="command",
                                excerpt=f"{name} architecture: {reported}",
                            ),
                        ),
                        detected=reported,
                        required=normalise_arch(facts.host_arch),
                        component=name,
                        remediation_hint=f"Prebuilt native addons for {name} are selected by "
                        "the runtime's own architecture. A mismatch means every one of them "
                        "is emulated, and any addon compiled here will not load in a native "
                        "process.",
                    )
                )

        return out

    def _libc_findings(self, facts: AbiFacts) -> list[Finding]:
        libc = facts.libc
        if libc is None or libc.flavour is None:
            return []

        evidence = (self.cmd_evidence(("ldd", "--version"), libc.raw or libc.flavour),)

        if libc.flavour == "musl":
            return [
                self.finding(
                    "abi/musl-libc",
                    FindingState.INFO,
                    "This machine uses musl libc, so manylinux wheels will not load here.",
                    evidence=evidence,
                    detected=f"musl {libc.version_text or 'unknown'}",
                    component="abi",
                    remediation_hint="pip does not report this: it skips the manylinux wheel "
                    "and builds from source instead, which needs a compiler and headers that "
                    "a slim image usually lacks. Install the `musllinux` build where one "
                    "exists, or add build tooling deliberately rather than discovering the "
                    "need mid-install.",
                )
            ]

        floor = dict(MANYLINUX_GLIBC)[COMMON_MANYLINUX]
        if libc.version and len(libc.version) >= 2 and (libc.version[0], libc.version[1]) < floor:
            supported = facts.supported_wheel_tags
            return [
                self.finding(
                    "abi/glibc-below-common-wheel-tag",
                    FindingState.WARN,
                    f"glibc {libc.version_text} is below the {COMMON_MANYLINUX} floor "
                    f"({floor[0]}.{floor[1]}).",
                    evidence=evidence,
                    detected=f"glibc {libc.version_text}",
                    required=f"glibc >={floor[0]}.{floor[1]}",
                    component="abi",
                    remediation_hint="Wheels carrying that tag are skipped, silently, and pip "
                    "builds from source instead -- which is how `pip install numpy` becomes a "
                    "fifteen-minute compile that fails on a missing header. "
                    + (
                        f"This machine can install: {', '.join(supported)}."
                        if supported
                        else "This machine can install no manylinux tag at all."
                    ),
                )
            ]

        return [
            self.finding(
                "abi/glibc-ok",
                FindingState.PASS,
                f"glibc {libc.version_text} accepts current manylinux wheels.",
                evidence=evidence,
                detected=f"glibc {libc.version_text}",
                component="abi",
            )
        ]
