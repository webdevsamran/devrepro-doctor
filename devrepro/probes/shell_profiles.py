"""Shell / tool-manager profile analysis.

Inspects PowerShell profiles and bash/zsh/fish configs *safely*: reads
only initialization-relevant lines, detects conflicting tool-manager
initialization (conda/pyenv/nvm/asdf/mise/Homebrew), and redacts personal
paths before anything is stored.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from devrepro.core.models import Evidence, FindingState, VirtualenvInfo
from devrepro.probes.base import Probe, ProbeResult
from devrepro.probes.helpers import read_text_safe

__all__ = ["ShellProfileProbe"]

_MANAGER_INIT_PATTERNS: dict[str, tuple[str, ...]] = {
    "conda": (r"conda\s+(shell\.|init|activate)", r"conda\.sh"),
    "pyenv": (r"pyenv\s+(init|shell|global|local)", r"pyenv-virtualenv-init"),
    "nvm": (r"source\s+.*nvm\.sh", r"\bnvm\b\s+(use|install)"),
    "fnm": (r"fnm\s+env",),
    "volta": (r"volta\s+(load|setup)",),
    "mise": (r"mise\s+activate",),
    "asdf": (r"asdf\.sh", r"asdf\s+(shell|global)"),
    "homebrew": (r"brew\s+shellenv", r"eval\s*\$\(.*/brew shellenv"),
}


def _profile_files(platform: str) -> list[Path]:
    home = Path.home()
    files: list[Path] = []
    if platform == "windows":
        for rel in (
            "Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1",
            "Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
        ):
            files.append(home / rel)
    else:
        shell = os.environ.get("SHELL", "")
        candidates = [".bashrc", ".bash_profile", ".profile"]
        if "zsh" in shell:
            candidates = [".zshrc", ".zprofile", ".zshenv"]
        elif "fish" in shell:
            candidates = ["config.fish"]
        for rel in candidates:
            files.append(home / rel)
    return files


def _redact_home(text: str, home: Path) -> str:
    return text.replace(str(home), "~")


class ShellProfileProbe(Probe):
    id = "shell/profiles"
    version = "1"

    def run(self) -> ProbeResult:
        findings = []
        managers_seen: dict[str, list[str]] = {}
        virtualenvs: list[VirtualenvInfo] = []
        home = Path.home()

        for path in _profile_files(self.ctx.platform):
            text = read_text_safe(path)
            if text is None:
                continue
            sanitized = _redact_home(text, home)
            for manager, patterns in _MANAGER_INIT_PATTERNS.items():
                hits = [
                    ln.strip()
                    for ln in sanitized.splitlines()
                    if any(re.search(p, ln) for p in patterns)
                ]
                if hits:
                    managers_seen.setdefault(manager, []).extend(hits[:3])

        active_kind: str | None = None
        env = self.ctx.env
        if env.get("CONDA_DEFAULT_ENV"):
            active_kind = "conda"
        elif env.get("VIRTUAL_ENV"):
            active_kind = "venv"
        elif env.get("NVM_DIR"):
            active_kind = "nvm"
        elif env.get("PYENV_VERSION") or env.get("PYENV_ROOT"):
            active_kind = "pyenv"
        elif env.get("VOLTA_HOME"):
            active_kind = "volta"
        elif env.get("MISE_TRUSTED_CONFIG_PATHS") or env.get("MISE_DIR"):
            active_kind = "mise"

        if active_kind:
            virtualenvs.append(VirtualenvInfo(kind=active_kind, active=True))

        conflicts = {m: hits for m, hits in managers_seen.items() if len(hits) > 0}
        multi_manager_conflict = {
            "python": {"conda", "pyenv"},
            "node": {"nvm", "fnm", "volta"},
        }
        for ecosystem, group in multi_manager_conflict.items():
            present = [m for m in group if m in conflicts]
            if len(present) > 1:
                findings.append(
                    self.finding(
                        f"{ecosystem}/manager-conflict",
                        FindingState.WARN,
                        f"Multiple {ecosystem} version managers initialize in your shell profiles: "
                        f"{', '.join(present)}. The last one to run wins unpredictably per-shell.",
                        evidence=(
                            Evidence(
                                source="file",
                                path="<profile>",
                                excerpt="; ".join(conflicts[p][0] for p in present),
                            ),
                        ),
                        detected=", ".join(present),
                        component=ecosystem,
                        remediation_hint="Pick one manager and remove the other's init lines "
                        "(LOW risk; edit your own profile).",
                    )
                )

        summary = ", ".join(sorted(managers_seen)) or "none"
        findings.append(
            self.finding(
                "shell/managers-initialized",
                FindingState.INFO,
                f"Tool-manager initialization found in shell profiles: {summary}.",
                evidence=(
                    Evidence(
                        source="file",
                        path="<profile>",
                        excerpt=f"managers={summary}; active={active_kind or 'none'}",
                    ),
                ),
                component="shell",
            )
        )

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={
                "managers": {m: h[:3] for m, h in managers_seen.items()},
                "active_manager": active_kind,
                "virtualenvs": [v.model_dump(mode="json") for v in virtualenvs],
            },
        )
