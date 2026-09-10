"""Whether this working tree is actually complete, and whether git can fetch.

Git fails quietly, which is why none of this is obvious from a failing build.

* A clone with LFS content and no LFS installed does not error. It writes
  pointer files -- a few lines of text where a binary should be -- and the
  failure arrives later as "not a valid image" or "unexpected end of archive",
  naming a file rather than a missing tool.
* A sparse checkout does not error either. The directory the build wants is
  simply not there, and `git status` is clean.
* A shallow clone breaks `git describe`, blame, and any diff against a base
  ref, with an error that mentions none of those.
* A credential helper that is configured but not installed turns every
  authenticated fetch into a prompt. In CI that is a hang and then a timeout.

Each is a five-second check here and an afternoon otherwise. Everything is read
from config and the filesystem; no helper is ever invoked, because several of
them block on stdin and a diagnostic that hangs waiting for a credential prompt
is worse than one that says nothing.
"""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.git.health import GitHealthReport, git_health
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["GitCheckoutProbe"]


def _evidence(excerpt: str) -> tuple[Evidence, ...]:
    return (Evidence(source="command", command=("git", "config"), excerpt=excerpt),)


class GitCheckoutProbe(Probe):
    id = "git/checkout"
    version = "1"

    def run(self) -> ProbeResult:
        root = self.ctx.project_dir or Path.cwd()
        report = git_health(root, runner=self.ctx.runner)

        if not report.is_repo:
            return ProbeResult(self.id, findings=(), data={"is_repo": False})

        findings = [*self._lfs(report), *self._completeness(report), *self._credentials(report)]

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={
                "is_repo": True,
                "lfs_required": report.lfs_required,
                "lfs_available": report.lfs_available,
                "lfs_initialised": report.lfs_initialised,
                "sparse_checkout": report.sparse_checkout,
                "sparse_pattern_count": report.sparse_pattern_count,
                "shallow": report.shallow,
                "partial_clone_filter": report.partial_clone_filter,
                "submodules_uninitialised": [
                    s.path for s in report.submodules if not s.initialized
                ],
                # Names and scopes only. A helper's stored value is never read.
                "credential_helpers": [
                    {"name": h.name, "scope": h.scope, "resolvable": h.resolvable}
                    for h in report.credential_helpers
                ],
            },
        )

    def _lfs(self, report: GitHealthReport) -> list[Finding]:
        if not report.lfs_required:
            return []

        if not report.lfs_available:
            return [
                self.finding(
                    "git/lfs-required-not-installed",
                    FindingState.BLOCKED,
                    "This repository tracks files with Git LFS, and git-lfs is not installed.",
                    evidence=(
                        Evidence(
                            source="file",
                            path=".gitattributes",
                            excerpt="declares filter=lfs",
                        ),
                    ),
                    required="git-lfs",
                    component="git",
                    remediation_hint="Install git-lfs, run `git lfs install`, then "
                    "`git lfs pull`. Until then the working tree holds pointer files "
                    "instead of content, and git reports the tree as clean.",
                )
            ]

        if not report.lfs_initialised:
            return [
                self.finding(
                    "git/lfs-not-initialised",
                    FindingState.ERROR,
                    "git-lfs is installed but its filters are not configured for this checkout.",
                    evidence=_evidence("filter.lfs.smudge is unset"),
                    detected=report.lfs_version,
                    required="filter.lfs.smudge",
                    component="git",
                    remediation_hint="`git lfs install` configures the filters, then "
                    "`git lfs pull` fetches what the current checkout missed. Installed "
                    "and initialised are different states with the same symptom.",
                )
            ]

        return [
            self.finding(
                "git/lfs-ready",
                FindingState.PASS,
                f"Git LFS {report.lfs_version} is installed and configured for this checkout.",
                evidence=_evidence("filter.lfs.smudge is set"),
                detected=report.lfs_version,
                component="git",
            )
        ]

    def _completeness(self, report: GitHealthReport) -> list[Finding]:
        out: list[Finding] = []

        uninitialised = [s.path for s in report.submodules if not s.initialized]
        if uninitialised:
            out.append(
                self.finding(
                    "git/submodules-uninitialised",
                    FindingState.ERROR,
                    f"{len(uninitialised)} declared submodule(s) are not initialised.",
                    evidence=(
                        Evidence(
                            source="file",
                            path=".gitmodules",
                            excerpt=", ".join(uninitialised[:5]),
                        ),
                    ),
                    detected=", ".join(uninitialised[:5]),
                    component="git",
                    remediation_hint="`git submodule update --init --recursive`. An "
                    "uninitialised submodule is an empty directory, so a build fails "
                    "on a missing file rather than on a missing submodule.",
                )
            )

        if report.sparse_checkout:
            count = report.sparse_pattern_count
            described = f"{count} pattern(s)" if count is not None else "an unread pattern list"
            out.append(
                self.finding(
                    "git/sparse-checkout-active",
                    FindingState.INFO,
                    f"Sparse checkout is active with {described}; parts of the tree are absent.",
                    evidence=_evidence("core.sparseCheckout=true"),
                    detected=described,
                    component="git",
                    remediation_hint="This is usually deliberate. It is reported because a "
                    "build failing on a path that exists in the repository and not on disk "
                    "has no other visible explanation: `git status` is clean either way. "
                    "`git sparse-checkout list` shows what is included.",
                )
            )

        if report.shallow:
            out.append(
                self.finding(
                    "git/shallow-clone",
                    FindingState.WARN,
                    "This is a shallow clone; history before the graft point is absent.",
                    evidence=(
                        Evidence(
                            source="command",
                            command=("git", "rev-parse", "--is-shallow-repository"),
                            excerpt="true",
                        ),
                    ),
                    component="git",
                    remediation_hint="`git fetch --unshallow`. Version strings derived from "
                    "`git describe`, `git blame`, and any diff against a base ref are wrong "
                    "or fail outright in a shallow clone, and none of them say why.",
                )
            )

        if report.partial_clone_filter:
            out.append(
                self.finding(
                    "git/partial-clone",
                    FindingState.INFO,
                    f"Partial clone with filter {report.partial_clone_filter}; "
                    "some objects are fetched on demand.",
                    evidence=_evidence(
                        f"remote.origin.partialclonefilter={report.partial_clone_filter}"
                    ),
                    detected=report.partial_clone_filter,
                    component="git",
                    remediation_hint="Operations that need a missing blob will reach the "
                    "network. On an air-gapped or offline machine they fail instead, which "
                    "looks like repository corruption rather than a missing fetch.",
                )
            )

        return out

    def _credentials(self, report: GitHealthReport) -> list[Finding]:
        out: list[Finding] = []

        missing = [h for h in report.credential_helpers if not h.resolvable]
        if missing:
            named = ", ".join(f"{h.name} ({h.scope})" for h in missing)
            out.append(
                self.finding(
                    "git/credential-helper-missing",
                    FindingState.WARN,
                    f"Configured credential helper(s) not found on this machine: {named}.",
                    evidence=_evidence(f"credential.helper={named}"),
                    detected=named,
                    component="git",
                    remediation_hint="Install the helper or clear the setting. A helper that "
                    "does not exist makes every authenticated fetch prompt for a password; "
                    "in CI that is a hang and then a timeout, with nothing naming the helper.",
                )
            )

        plaintext = [h for h in report.credential_helpers if h.plaintext]
        if plaintext:
            out.append(
                self.finding(
                    "git/credential-store-plaintext",
                    FindingState.INFO,
                    "The `store` credential helper keeps tokens in a plain-text file.",
                    evidence=_evidence("credential.helper=store"),
                    detected="store",
                    component="git",
                    remediation_hint="`~/.git-credentials` is unencrypted and world-readable "
                    "on some systems. Prefer an OS keychain helper. devrepro reports the "
                    "setting and never reads the file.",
                )
            )

        return out
