"""Real-time scanning on a build tree, and the trade this will not make for you.

On Windows, Defender's real-time protection inspects every file a build opens.
A dependency install opens hundreds of thousands, and each one is a synchronous
scan on a file that was written seconds earlier by a tool the machine already
trusts. This is routinely the largest single factor in "the same build takes
four times longer on Windows", and it is invisible: nothing fails, nothing logs,
the CPU graph shows a service nobody associates with the build.

**The advice here is deliberately not a recommendation.** Excluding a directory
from real-time scanning is a genuine reduction in protection, and a source tree
is not a safe place to make that trade blindly: `npm install` executes install
scripts from packages the user did not read. Whether the speed is worth it
depends on what the machine does and what the organisation requires, and this
tool has no view on either. So the output is a measurement -- what is excluded,
and what a build touches that is not -- plus the exact command, stated as
something to consider, not something to run.

Nothing here changes a setting. `Set-MpPreference` never appears.

Reading the current exclusions usually requires elevation. That is reported as
"could not read", not as "nothing is excluded" -- the two look identical from a
non-elevated shell and lead to opposite conclusions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "HOT_DIRECTORIES",
    "DefenderState",
    "ExclusionAdvice",
    "advise",
    "parse_exclusion_paths",
    "parse_realtime_status",
]

#: Directories a build hammers. Not the whole project: `node_modules` and the
#: package caches are where the file count actually is, and a narrower
#: exclusion is a smaller reduction in protection than excluding a source tree
#: somebody is also editing.
HOT_DIRECTORIES: tuple[tuple[str, str], ...] = (
    ("node_modules", "npm/pnpm/yarn install writes and reads hundreds of thousands of files"),
    (".venv", "every Python import in a virtualenv is a file open"),
    ("target", "cargo rebuilds touch the whole target directory"),
    ("build", "compiler output, rewritten on every build"),
    (".gradle", "Gradle's cache and daemon state"),
    ("obj", "MSBuild intermediate output"),
    ("bin", "MSBuild final output"),
)


@dataclass(frozen=True)
class DefenderState:
    """What Defender says about itself, or that it would not say."""

    #: `None` when the query failed, which on a non-elevated shell is the
    #: normal case and must not be confused with "off".
    realtime_enabled: bool | None = None
    exclusions: tuple[str, ...] = ()
    #: Why the query produced nothing, when it produced nothing.
    unavailable_because: str | None = None

    @property
    def readable(self) -> bool:
        return self.unavailable_because is None


_TRUE = re.compile(r"\b(True|Enabled)\b", re.IGNORECASE)
_FALSE = re.compile(r"\b(False|Disabled)\b", re.IGNORECASE)


def parse_realtime_status(text: str) -> bool | None:
    """Read a `Get-MpComputerStatus -Property RealTimeProtectionEnabled` answer.

    `None` for anything that is not clearly one or the other. A garbled or
    empty answer read as `False` would tell somebody their antivirus is off.
    """
    body = (text or "").strip()
    if not body:
        return None
    if _TRUE.search(body):
        return True
    if _FALSE.search(body):
        return False
    return None


def parse_exclusion_paths(text: str) -> tuple[str, ...]:
    """Read the `ExclusionPath` list out of a PowerShell answer.

    One per line, which is what `(Get-MpPreference).ExclusionPath` prints.
    Blank output means either no exclusions or no permission to look; the
    caller keeps those apart, because this function cannot.
    """
    return tuple(
        line.strip()
        for line in (text or "").splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def _covered(path: str, exclusions: tuple[str, ...]) -> bool:
    target = path.replace("/", "\\").rstrip("\\").lower()
    for raw in exclusions:
        excluded = raw.replace("/", "\\").rstrip("\\").lower()
        if not excluded:
            continue
        if target == excluded or target.startswith(excluded + "\\"):
            return True
    return False


@dataclass(frozen=True)
class ExclusionAdvice:
    """What a build touches, what is already excluded, and the trade involved."""

    #: Directories present in the project that real-time scanning will inspect.
    unexcluded: tuple[tuple[str, str], ...] = ()
    already_excluded: tuple[str, ...] = ()
    #: The command to add them, for a person who decides the trade is worth it.
    command: str | None = None
    #: Present when Defender's configuration could not be read at all -- almost
    #: always a permissions answer.
    unknown_because: str | None = None
    #: Present when Defender answered and said its real-time protection is off.
    #: A *known* fact, kept apart from `unknown_because` because the two lead
    #: somewhere different: one wants an elevated shell, the other wants you to
    #: know a different product is probably doing the scanning.
    inactive_because: str | None = None


def advise(
    state: DefenderState,
    project_root: str,
    present_directories: tuple[str, ...],
) -> ExclusionAdvice:
    """Compare what the build touches against what Defender already skips.

    `present_directories` are the hot directories that actually exist -- the
    caller checks, so this never guesses that a project has a `target/` because
    it might. They may be relative paths (`web/node_modules`), because a
    workspace keeps its dependencies one level down.
    """
    if not state.readable:
        return ExclusionAdvice(unknown_because=state.unavailable_because)
    if state.realtime_enabled is False:
        return ExclusionAdvice(
            inactive_because=(
                "Defender's real-time protection is off, so its exclusion list "
                "changes nothing. On a machine that is not unprotected, this usually "
                "means another antivirus product registered itself and Defender "
                "stood down -- and that product's exclusions are not visible from "
                "here, so this check cannot speak for whatever is actually scanning "
                "your build directories."
            )
        )

    root = project_root.rstrip("\\/")
    reasons = dict(HOT_DIRECTORIES)
    unexcluded: list[tuple[str, str]] = []
    covered: list[str] = []
    for name in present_directories:
        # `name` may be `web/node_modules`; the reason is keyed by the leaf.
        leaf = name.rsplit("/", 1)[-1]
        full = root + "\\" + name.replace("/", "\\")
        if _covered(full, state.exclusions):
            covered.append(full)
        else:
            unexcluded.append((full, reasons.get(leaf, "touched heavily during a build")))

    command = None
    if unexcluded:
        paths = ",".join(f"'{path}'" for path, _ in unexcluded)
        command = f"Add-MpPreference -ExclusionPath {paths}"

    return ExclusionAdvice(
        unexcluded=tuple(unexcluded),
        already_excluded=tuple(covered),
        command=command,
    )
