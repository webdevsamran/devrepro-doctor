"""Hygiene probe: filesystem and locale facts that break checkouts.

These findings are deliberately low-severity. None of them is broken on its
own -- a case-insensitive filesystem is the default on two of three major
platforms -- but each one changes what a repository does when it moves between
machines, which is the question this project exists to answer.
"""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["HygieneProbe"]


class HygieneProbe(Probe):
    id = "system/hygiene"
    version = "1"

    def run(self) -> ProbeResult:
        from devrepro.platforms.hygiene import (
            detect_case_sensitivity,
            locale_info,
            reserved_name_conflicts,
            symlink_support,
        )

        root = self.ctx.project_dir or Path.cwd()
        findings = []
        data: dict[str, object] = {}

        case = detect_case_sensitivity(root)
        data["case_sensitive"] = case.sensitive
        if case.sensitive is not None:
            findings.append(
                self.finding(
                    "hygiene/filesystem-case",
                    FindingState.INFO,
                    "Filesystem is case-{}.".format(
                        "sensitive" if case.sensitive else "insensitive"
                    ),
                    evidence=(Evidence(source="file", path=str(root), excerpt=case.detail),),
                    detected="case-sensitive" if case.sensitive else "case-insensitive",
                    component="filesystem",
                    remediation_hint=None
                    if case.sensitive
                    else "Two files whose names differ only in case collapse into one "
                    "here. A repository authored on a case-sensitive system can "
                    "lose a file on checkout without any error.",
                )
            )

        reserved = reserved_name_conflicts(root)
        data["reserved_names"] = reserved
        if reserved:
            findings.append(
                self.finding(
                    "hygiene/reserved-filename",
                    FindingState.ERROR,
                    f"{len(reserved)} path(s) use names Windows reserves.",
                    evidence=(
                        Evidence(
                            source="file",
                            path=str(root),
                            excerpt=", ".join(reserved[:5]),
                        ),
                    ),
                    detected=", ".join(reserved[:5]),
                    component="filesystem",
                    remediation_hint="Rename these paths. Windows refuses reserved device "
                    "names with or without an extension, so this repository cannot be "
                    "checked out there at all.",
                )
            )

        symlinks = symlink_support()
        data["symlinks_supported"] = symlinks.supported
        if symlinks.supported is False:
            findings.append(
                self.finding(
                    "hygiene/symlinks-unavailable",
                    FindingState.WARN,
                    "Symlink creation is not available to this process.",
                    evidence=(Evidence(source="system", excerpt=symlinks.detail),),
                    component="filesystem",
                    remediation_hint="Enable Developer Mode, or clone with "
                    "`git config core.symlinks true` only if the privilege is held. "
                    "Otherwise git writes symlinks as ordinary text files and the "
                    "working tree silently differs from the commit.",
                )
            )

        loc = locale_info(dict(self.ctx.env))
        data["locale"] = {
            "preferred_encoding": loc.preferred_encoding,
            "filesystem_encoding": loc.filesystem_encoding,
            "is_utf8": loc.is_utf8,
        }
        if not loc.is_utf8:
            findings.append(
                self.finding(
                    "hygiene/non-utf8-locale",
                    FindingState.WARN,
                    f"Preferred text encoding is {loc.preferred_encoding}, not UTF-8.",
                    evidence=(Evidence(source="system", excerpt=loc.detail),),
                    detected=loc.preferred_encoding,
                    required="UTF-8",
                    component="locale",
                    remediation_hint="Set PYTHONUTF8=1, or the OS-wide UTF-8 option, if "
                    "tools fail on non-ASCII output. This is the usual cause of a "
                    "UnicodeEncodeError that appears on one machine only.",
                )
            )

        return ProbeResult(self.id, findings=tuple(findings), data=data)
