"""Three host-level facts that make builds slow or wrong, and nothing reports.

Grouped into one probe because they share a shape: each is a property of the
*machine* that no tool in the build chain can see, each produces a symptom that
points somewhere else entirely, and none of them makes anything fail outright.

- **Where the source tree lives.** A WSL shell working under `/mnt/c`, or a
  project on an SMB share, pays a millisecond per file operation instead of a
  microsecond. A dependency install performs hundreds of thousands of them.
- **Whether real-time scanning inspects the build directories.** On Windows,
  Defender scans every file a build opens, synchronously.
- **Where the clock gets its time.** Skew is already detected elsewhere; this
  asks whether anything is correcting the clock at all, because a machine with
  no time source is not skewed *yet*.

Every command run here is a query. Nothing is written, nothing is measured by
doing work on the volume, and no setting is changed -- the Defender advice
prints the command and stops, because excluding a source tree from real-time
scanning is a real reduction in protection and not this tool's decision.
"""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.platforms.antivirus import (
    HOT_DIRECTORIES,
    DefenderState,
    advise,
    parse_exclusion_paths,
    parse_realtime_status,
)
from devrepro.platforms.mounts import classify_path, parse_proc_mounts
from devrepro.platforms.timesync import (
    TimeSync,
    parse_chronyc_tracking,
    parse_timedatectl,
    parse_w32tm_failure,
    parse_w32tm_status,
)
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["HostPerfProbe"]

_PS = ("powershell", "-NoProfile", "-Command")

#: Separates the two answers in the combined query. A string no path and no
#: boolean can contain, so splitting on it cannot cut a value in half.
_SENTINEL = "--devrepro--"

#: Both Defender questions in one interpreter start. `-ErrorAction
#: SilentlyContinue` on the second keeps a permissions failure on the
#: exclusion list from discarding the real-time answer, which is the half that
#: decides whether the exclusion list means anything at all.
_DEFENDER_QUERY = (
    "(Get-MpComputerStatus).RealTimeProtectionEnabled; "
    "Write-Output '" + _SENTINEL + "'; "
    "(Get-MpPreference -ErrorAction SilentlyContinue).ExclusionPath"
)

#: How far down to look for build directories. One level, because a workspace
#: keeps its `node_modules` in `web/` or `packages/api/` and the root-only check
#: missed the largest directory in this project's own repository. Not deeper:
#: the walk is on the hot path of every scan, and nested `node_modules` are
#: inside a directory this already names.
_WORKSPACE_DEPTH = 1

#: Never descended into while looking for workspaces.
_SKIP = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "target"})


def _hot_directories(root: Path) -> tuple[str, ...]:
    """Build directories that exist, at the root or one workspace down.

    Returns paths relative to `root`, so the advice names the actual directory
    rather than a name that appears three times in the tree.
    """
    names = [name for name, _reason in HOT_DIRECTORIES]
    found: list[str] = [name for name in names if (root / name).is_dir()]
    if _WORKSPACE_DEPTH:
        try:
            children = [c for c in root.iterdir() if c.is_dir() and c.name not in _SKIP]
        except OSError:  # pragma: no cover - unreadable project root
            children = []
        for child in sorted(children):
            found.extend(f"{child.name}/{name}" for name in names if (child / name).is_dir())
    return tuple(found)


class HostPerfProbe(Probe):
    id = "host/performance"
    version = "1"

    def run(self) -> ProbeResult:
        findings: list[Finding] = []
        data: dict[str, object] = {}

        mount = self._filesystem(findings, data)
        self._antivirus(findings, data)
        self._clock_source(findings, data)

        data["mount_kind"] = mount
        return ProbeResult(self.id, findings=tuple(findings), data=data)

    # ------------------------------------------------------------- filesystem

    def _filesystem(self, findings: list[Finding], data: dict[str, object]) -> str:
        root = str(self.ctx.project_dir or Path.cwd())
        mounts: tuple[tuple[str, str], ...] = ()
        if self.ctx.platform != "windows":
            # /proc/mounts on Linux, `mount` elsewhere. Read, never mounted.
            result = self.ctx.runner.run(("cat", "/proc/mounts"), timeout=5)
            if not result.ok:
                result = self.ctx.runner.run(("mount",), timeout=5)
            if result.ok:
                mounts = parse_proc_mounts(result.stdout)

        verdict = classify_path(
            root,
            platform=self.ctx.platform,
            is_wsl=self.ctx.platform_info.is_wsl,
            mounts=mounts,
        )
        data["filesystem"] = {"kind": verdict.kind, "slow": verdict.slow}

        if verdict.slow:
            findings.append(
                self.finding(
                    "host/slow-filesystem",
                    FindingState.WARN,
                    verdict.detail,
                    evidence=(
                        Evidence(
                            source="system",
                            excerpt=f"project filesystem: {verdict.kind}",
                        ),
                    ),
                    detected=verdict.kind,
                    component="filesystem",
                    remediation_hint=verdict.remedy,
                )
            )
        return verdict.kind

    # -------------------------------------------------------------- antivirus

    def _antivirus(self, findings: list[Finding], data: dict[str, object]) -> None:
        if self.ctx.platform != "windows":
            return

        # The cheap check gates the expensive one. With no dependency or output
        # directories there is nothing to advise about, and spawning PowerShell
        # to discover that afterwards is most of what this probe used to cost.
        root = Path(self.ctx.project_dir or Path.cwd())
        present = _hot_directories(root)
        if not present:
            return

        # One PowerShell session, two questions. Starting the interpreter costs
        # more than either query, and `devrepro bench` put this probe at 5.3
        # seconds on a machine where nothing was wrong.
        answer = self.ctx.runner.run((*_PS, _DEFENDER_QUERY), timeout=30)
        if not answer.ok:
            # Almost always a permissions answer rather than an absent Defender,
            # and "could not read" must not render as "nothing is excluded".
            state = DefenderState(
                unavailable_because=(
                    "Defender's configuration could not be read from this shell; "
                    "Get-MpComputerStatus usually needs an elevated session."
                )
            )
        else:
            realtime, _, exclusions = answer.stdout.partition(_SENTINEL)
            state = DefenderState(
                realtime_enabled=parse_realtime_status(realtime),
                exclusions=parse_exclusion_paths(exclusions),
            )

        advice = advise(state, str(root), present)
        data["defender"] = {
            "readable": state.readable,
            "realtime": state.realtime_enabled,
            "unexcluded": [path for path, _ in advice.unexcluded],
        }

        if advice.unknown_because:
            findings.append(
                self.finding(
                    "host/antivirus-unknown",
                    FindingState.UNKNOWN,
                    advice.unknown_because,
                    evidence=(
                        Evidence(
                            source="command",
                            command=("powershell", "Get-MpComputerStatus"),
                            excerpt="query did not answer",
                        ),
                    ),
                    component="antivirus",
                    remediation_hint=(
                        "Run `devrepro doctor` from an elevated shell to see which "
                        "build directories real-time scanning inspects."
                    ),
                )
            )
            return

        if advice.inactive_because:
            # Distinct from the unknown case: Defender answered. Reporting this
            # as UNKNOWN with advice to elevate -- which the first version did --
            # gets both the category and the remedy wrong.
            findings.append(
                self.finding(
                    "host/antivirus-not-defender",
                    FindingState.INFO,
                    advice.inactive_because,
                    evidence=(
                        Evidence(
                            source="command",
                            command=(
                                "powershell",
                                "(Get-MpComputerStatus).RealTimeProtectionEnabled",
                            ),
                            excerpt="RealTimeProtectionEnabled: False",
                        ),
                    ),
                    component="antivirus",
                    remediation_hint=(
                        "If a Windows build here is several times slower than the same "
                        "build elsewhere, check your antivirus product's own exclusion "
                        "list for the project's dependency and output directories."
                    ),
                )
            )
            return

        if advice.unexcluded:
            listed = "; ".join(f"{path} ({reason})" for path, reason in advice.unexcluded)
            findings.append(
                self.finding(
                    "host/antivirus-scans-build-dirs",
                    FindingState.INFO,
                    (
                        f"Real-time scanning inspects {len(advice.unexcluded)} build "
                        "directory tree(s) in this project. Every file a build opens is "
                        "scanned synchronously, which is routinely the largest single "
                        "factor in a Windows build being several times slower than the "
                        "same build elsewhere."
                    ),
                    evidence=(Evidence(source="system", excerpt=listed),),
                    component="antivirus",
                    remediation_hint=(
                        "Excluding these is a real reduction in protection, on a tree "
                        "whose install scripts execute code you did not write -- it is "
                        "a trade, and whether it is worth it depends on the machine and "
                        "on your organisation's rules. DevRepro changes nothing. If you "
                        "decide it is: " + (advice.command or "")
                    ),
                )
            )

    # ------------------------------------------------------------ clock source

    def _clock_source(self, findings: list[Finding], data: dict[str, object]) -> None:
        sync = TimeSync()
        if self.ctx.platform == "windows":
            result = self.ctx.runner.run(("w32tm", "/query", "/status"), timeout=15)
            if result.ok:
                sync = parse_w32tm_status(result.stdout)
            else:
                # A stopped Windows Time service reports itself by failing, so
                # the failure path is where this check most often finds its
                # answer. Reading only `result.ok` discarded exactly the
                # machines the check exists for.
                sync = parse_w32tm_failure(result.stdout + result.stderr) or sync
        else:
            result = self.ctx.runner.run(("timedatectl", "status"), timeout=10)
            if result.ok:
                sync = parse_timedatectl(result.stdout)
            else:
                chrony = self.ctx.runner.run(("chronyc", "tracking"), timeout=10)
                if chrony.ok:
                    sync = parse_chronyc_tracking(chrony.stdout)

        data["time_sync"] = {
            "synchronised": sync.synchronised,
            "source": sync.source,
            "self_referential": sync.self_referential,
        }

        if not sync.actionable:
            return

        findings.append(
            self.finding(
                "host/clock-unsynchronised",
                FindingState.WARN,
                sync.detail or "Nothing is correcting this machine's clock.",
                evidence=(
                    Evidence(
                        source="command",
                        command=("w32tm", "/query", "/status")
                        if self.ctx.platform == "windows"
                        else ("timedatectl", "status"),
                        excerpt=f"source={sync.source or 'none'}",
                    ),
                ),
                detected=sync.source,
                component="clock",
                remediation_hint=(
                    "A clock left uncorrected drifts, and the first symptom is usually "
                    "a TLS error that blames a certificate -- 'not yet valid' or "
                    "'expired' on a certificate that is fine. On Windows: `w32tm "
                    "/config /syncfromflags:domhier /update` on a domain machine, or "
                    "point it at time.windows.com. On Linux: enable systemd-timesyncd "
                    "or chrony."
                ),
            )
        )
