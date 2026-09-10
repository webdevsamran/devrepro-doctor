"""Build orchestrators and formatter configuration, read from the repository.

Two questions that are properties of the *project* rather than the machine, and
both are answered from files already on disk.

- Which monorepo orchestrator is in use, whether it has a remote cache, and
  whether a cache credential is sitting in a committed file.
- Whether the editor and the formatter have been told different things, which
  produces whitespace diffs nobody can attribute and a reviewer eventually
  blames on the author.

Neither runs anything. `nx show projects` and `bazel info` start daemons, and a
formatter run would rewrite files -- both are the opposite of what a diagnostic
does.
"""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.probes.base import Probe, ProbeResult
from devrepro.project.buildtools import detect_build_tools
from devrepro.project.editorconfig import (
    compare_styles,
    read_editorconfig,
    read_prettier,
    read_ruff,
)

__all__ = ["ProjectToolingProbe"]


class ProjectToolingProbe(Probe):
    id = "project/tooling"
    version = "1"

    def supported(self) -> bool:
        return self.ctx.project_dir is not None or Path.cwd().is_dir()

    def run(self) -> ProbeResult:
        root = Path(self.ctx.project_dir or Path.cwd())
        findings: list[Finding] = []
        data: dict[str, object] = {}

        findings.extend(self._build_tools(root, data))
        findings.extend(self._formatters(root, data))
        return ProbeResult(self.id, findings=tuple(findings), data=data)

    # --------------------------------------------------------- orchestrators

    def _build_tools(self, root: Path, data: dict[str, object]) -> list[Finding]:
        tools = detect_build_tools(root)
        data["build_tools"] = [
            {
                "name": t.name,
                "config": t.config_path,
                "remote_cache": t.cache.remote_configured,
                "credential_field": t.cache.credential_field,
            }
            for t in tools
        ]
        if not tools:
            return []

        findings: list[Finding] = [
            self.finding(
                "buildtools/detected",
                FindingState.INFO,
                "Monorepo orchestration: "
                + ", ".join(
                    f"{t.name} ({'remote cache' if t.cache.remote_configured else 'local cache'})"
                    for t in tools
                ),
                evidence=(
                    Evidence(
                        source="file",
                        path=tools[0].config_path,
                        excerpt="; ".join(f"{t.name}: {t.cache.detail}" for t in tools),
                    ),
                ),
                component="build",
            )
        ]

        for tool in tools:
            if not tool.cache.credential_field:
                continue
            findings.append(
                self.finding(
                    f"{tool.name}/cache-credential-committed",
                    FindingState.WARN,
                    (
                        f"{tool.config_path} sets `{tool.cache.credential_field}`, which "
                        "is a build-cache credential in a file with a git history. A "
                        "read-write cache token lets whoever holds it write entries that "
                        "every developer and every CI run then treats as trusted build "
                        "output."
                    ),
                    evidence=(
                        Evidence(
                            source="file",
                            path=tool.config_path,
                            # The field name, never the value. The finding is
                            # that a secret-shaped field is committed, and that
                            # is the whole of what anyone needs to act.
                            excerpt=f"field present: {tool.cache.credential_field}",
                        ),
                    ),
                    component="build",
                    remediation_hint=(
                        "Move it to an environment variable and rotate it -- it is in "
                        "the history whether or not you remove it now. Both Nx and "
                        "Bazel read the credential from the environment."
                    ),
                )
            )
        return findings

    # ------------------------------------------------------------ formatters

    def _formatters(self, root: Path, data: dict[str, object]) -> list[Finding]:
        configs = (
            read_editorconfig(root / ".editorconfig"),
            read_prettier(root),
            read_ruff(root),
        )
        conflicts = compare_styles(configs)
        data["style_conflicts"] = [c.describe() for c in conflicts]
        if not conflicts:
            return []

        return [
            self.finding(
                "editor/style-conflict",
                FindingState.WARN,
                (
                    f"{len(conflicts)} disagreement(s) between the editor's declared "
                    "style and a formatter's: "
                    + "; ".join(c.describe() for c in conflicts)
                    + ". The editor formats one way, the formatter rewrites it the "
                    "other, and the result is a whitespace diff nobody can attribute."
                ),
                evidence=(
                    Evidence(
                        source="file",
                        path=".editorconfig",
                        excerpt="; ".join(c.describe() for c in conflicts),
                    ),
                ),
                component="editor",
                remediation_hint=(
                    "Pick one and make the other follow it. Whichever tool runs in CI "
                    "is the one that decides, so `.editorconfig` should usually be "
                    "changed to match the formatter rather than the reverse."
                ),
            )
        ]
