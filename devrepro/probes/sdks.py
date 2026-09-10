"""Which SDKs are installed, not just which one answers first.

`dotnet --version` and `java -version` report the one the shell resolves. That
is the wrong question for two ecosystems that install several side by side and
select between them per project.

* **`global.json` pins an exact .NET SDK.** With `rollForward` unset the pin is
  exact, so a machine carrying 9.0.101 and a repository asking for 8.0.100
  fails at `dotnet build` with "A compatible .NET SDK was not found" -- while
  `dotnet --version` cheerfully prints 9.0.101 and every other check passes.
* **`JAVA_HOME` and the `java` on PATH are separate settings.** Maven and
  Gradle use `JAVA_HOME`; a shell script that calls `java` directly uses PATH.
  When they disagree the build compiles against one JDK and runs on another,
  and the error is a `UnsupportedClassVersionError` naming neither.

Only versions are recorded. `dotnet --list-sdks` prints an install path beside
each version, and on Windows that path is frequently under a user profile.
"""

from __future__ import annotations

import re
from pathlib import Path

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.probes.base import Probe, ProbeResult
from devrepro.probes.helpers import read_text_safe

__all__ = ["SdkProbe", "parse_dotnet_sdks", "satisfies_global_json"]

#: `8.0.100 [/usr/share/dotnet/sdk]` -- the version, then a path that is
#: deliberately discarded.
_SDK_LINE = re.compile(r"^([0-9]+\.[0-9]+\.[0-9][\w.\-]*)\s+\[", re.MULTILINE)


def parse_dotnet_sdks(text: str) -> tuple[str, ...]:
    """Versions from `dotnet --list-sdks`, without the paths beside them."""
    return tuple(dict.fromkeys(_SDK_LINE.findall(text or "")))


def satisfies_global_json(
    pinned: str, installed: tuple[str, ...], roll_forward: str | None
) -> bool:
    """Would `dotnet` accept one of these SDKs for this `global.json`?

    A deliberately partial model of .NET's resolution. `rollForward` has eight
    documented policies and this covers the three that decide the common cases;
    anything else is treated as "some newer SDK will do", because the failure
    mode of guessing *permissively* here is a missing finding, and guessing
    restrictively would block a build that works.
    """
    if not installed:
        return False
    if pinned in installed:
        return True

    policy = (roll_forward or "").lower()
    if policy in {"", "disable"}:
        # Unset means `latestPatch` for a pinned version in modern SDKs, but a
        # patch-level match still has to share major.minor.feature.
        return any(_same_feature_band(pinned, candidate) for candidate in installed)
    if policy in {"latestpatch"}:
        return any(_same_feature_band(pinned, candidate) for candidate in installed)
    if policy in {"major", "latestmajor"}:
        return True
    # `feature`, `minor`, `latestminor` and anything unrecognised: something at
    # or above the pin will do.
    return any(_at_least(candidate, pinned) for candidate in installed)


def _parts(version: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for chunk in version.split("-", maxsplit=1)[0].split("."):
        if chunk.isdigit():
            numbers.append(int(chunk))
        else:
            break
    return tuple(numbers)


def _same_feature_band(pinned: str, candidate: str) -> bool:
    """.NET SDK versions are `major.minor.feature+patch`: 8.0.1xx is one band."""
    a, b = _parts(pinned), _parts(candidate)
    if len(a) < 3 or len(b) < 3:
        return False
    return a[0] == b[0] and a[1] == b[1] and a[2] // 100 == b[2] // 100 and b[2] >= a[2]


def _at_least(candidate: str, pinned: str) -> bool:
    return _parts(candidate) >= _parts(pinned)


class SdkProbe(Probe):
    id = "sdk/installed"
    version = "1"

    def run(self) -> ProbeResult:
        findings: list[Finding] = []
        sdks = self._dotnet_sdks()
        findings.extend(self._dotnet_findings(sdks))
        java = self._java_homes()
        findings.extend(self._java_findings(java))

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={
                "dotnet_sdks": list(sdks),
                "java_home_set": java["home"] is not None,
                "java_home_matches_path": java["matches"],
                "jdk_count": java["count"],
            },
        )

    # ---------------------------------------------------------------- dotnet

    def _dotnet_sdks(self) -> tuple[str, ...]:
        result = self.ctx.runner.run(("dotnet", "--list-sdks"), timeout=15)
        return parse_dotnet_sdks(result.stdout) if result.ok else ()

    def _dotnet_findings(self, sdks: tuple[str, ...]) -> list[Finding]:
        root = self.ctx.project_dir or Path.cwd()
        text = read_text_safe(root / "global.json")
        if text is None:
            return []

        import json

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # `detect_requirements` already reports an unparseable global.json;
            # saying it twice would be two findings for one problem.
            return []

        sdk_block = data.get("sdk")
        pinned = sdk_block.get("version") if isinstance(sdk_block, dict) else None
        if not isinstance(pinned, str) or not pinned:
            return []
        roll_forward = sdk_block.get("rollForward") if isinstance(sdk_block, dict) else None

        evidence = (Evidence(source="file", path="global.json", excerpt=f"sdk.version={pinned}"),)

        if not sdks:
            return [
                self.finding(
                    "dotnet/sdk-list-unavailable",
                    FindingState.UNKNOWN,
                    "global.json pins a .NET SDK, but the installed SDKs could not be listed.",
                    evidence=evidence,
                    required=pinned,
                    component="dotnet",
                    remediation_hint="`dotnet --list-sdks` did not answer, so whether the "
                    "pinned SDK is present is unknown. Install the .NET SDK, or ignore this "
                    "if the project is not built here.",
                )
            ]

        policy = roll_forward if isinstance(roll_forward, str) else None
        if satisfies_global_json(pinned, sdks, policy):
            return [
                self.finding(
                    "dotnet/global-json-satisfied",
                    FindingState.PASS,
                    f"An installed .NET SDK satisfies global.json ({pinned}).",
                    evidence=evidence,
                    detected=", ".join(sdks),
                    required=pinned,
                    component="dotnet",
                )
            ]

        return [
            self.finding(
                "dotnet/global-json-sdk-missing",
                FindingState.BLOCKED,
                f"global.json pins .NET SDK {pinned}; installed: {', '.join(sdks)}.",
                evidence=evidence,
                detected=", ".join(sdks),
                required=pinned,
                component="dotnet",
                remediation_hint="`dotnet build` fails with 'A compatible .NET SDK was not "
                "found' while `dotnet --version` prints one of the installed SDKs, which is "
                "why this looks like a working install. Install the pinned SDK, or set "
                "`rollForward` in global.json if a newer one is acceptable.",
            )
        ]

    # ------------------------------------------------------------------ java

    def _java_homes(self) -> dict[str, object]:
        home = self.ctx.env.get("JAVA_HOME") or None
        matches: bool | None = None

        if home:
            # Compare what JAVA_HOME's java reports against what PATH's java
            # reports. Comparing paths would be wrong on a machine where one is
            # a symlink to the other, which is the normal case.
            suffix = ".exe" if self.ctx.platform == "windows" else ""
            candidate = Path(home) / "bin" / f"java{suffix}"
            from_home = self.ctx.runner.run((str(candidate), "-version"), timeout=15)
            from_path = self.ctx.runner.run(("java", "-version"), timeout=15)
            if from_home.ok and from_path.ok:
                matches = _java_version(from_home) == _java_version(from_path)

        candidates = 0
        for directory in (
            Path.home() / ".sdkman" / "candidates" / "java",
            Path("/usr/lib/jvm"),
            Path("/Library/Java/JavaVirtualMachines"),
        ):
            try:
                candidates += sum(1 for entry in directory.iterdir() if entry.is_dir())
            except OSError:
                continue

        return {"home": home, "matches": matches, "count": candidates}

    def _java_findings(self, java: dict[str, object]) -> list[Finding]:
        out: list[Finding] = []

        if java["matches"] is False:
            out.append(
                self.finding(
                    "java/home-path-mismatch",
                    FindingState.WARN,
                    "JAVA_HOME and the `java` on PATH are different JDKs.",
                    evidence=(
                        Evidence(
                            source="env",
                            excerpt="JAVA_HOME/bin/java and PATH java report different versions",
                        ),
                    ),
                    component="java",
                    remediation_hint="Maven and Gradle use JAVA_HOME; a shell script calling "
                    "`java` uses PATH. When they disagree the build compiles against one JDK "
                    "and runs on another, and the failure is an "
                    "UnsupportedClassVersionError that names neither.",
                )
            )

        count = java["count"]
        if isinstance(count, int) and count > 1:
            out.append(
                self.finding(
                    "java/multiple-jdks",
                    FindingState.INFO,
                    f"{count} JDK installations found in the usual locations.",
                    evidence=(Evidence(source="file", excerpt=f"{count} JDK directories"),),
                    detected=str(count),
                    component="java",
                    remediation_hint="Which one a build uses depends on JAVA_HOME, on PATH, "
                    "and on whichever toolchain block the build file declares -- three "
                    "settings that are frequently out of step.",
                )
            )

        return out


def _java_version(result: object) -> str | None:
    """`java -version` writes to stderr, which is the usual reason it looks empty."""
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    match = re.search(r'version "([\w.\-+]+)"', stdout + stderr)
    return match.group(1) if match else None
