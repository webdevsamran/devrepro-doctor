"""Toolchain detection: a declarative table of developer tools, resolved
against PATH with version extraction and best-effort install-source
heuristics. Duplicate installations are reported, never hidden.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING

from devrepro.core.models import Evidence, Finding, FindingState, ToolInstallation
from devrepro.probes.base import Probe, ProbeResult
from devrepro.probes.helpers import extract_version, resolve_all_on_path

if TYPE_CHECKING:
    from devrepro.core.runner import CommandRunner

__all__ = ["COMPILER_SPECS", "TOOL_SPECS", "ToolSpec", "ToolchainProbe", "detect_toolchain"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    commands: tuple[str, ...]
    version_args: tuple[str, ...]
    category: str  # runtime | tool | compiler | container | cloud | pkg-manager
    version_regex: str | None = None


TOOL_SPECS: tuple[ToolSpec, ...] = (
    # --- version control / collaboration ---------------------------------
    ToolSpec("git", ("git",), ("--version",), "tool", r"git version (\d[\w.\-+]*)"),
    ToolSpec("gh", ("gh",), ("--version",), "tool", r"gh version (\d[\w.\-+]*)"),
    # --- language runtimes ------------------------------------------------
    ToolSpec(
        "python", ("python", "python3"), ("--version",), "runtime", r"[Pp]ython (\d[\w.\-+]*)"
    ),
    ToolSpec("node", ("node",), ("--version",), "runtime", r"v(\d[\w.\-+]*)"),
    ToolSpec("npm", ("npm",), ("--version",), "tool"),
    ToolSpec("pnpm", ("pnpm",), ("--version",), "tool"),
    ToolSpec("yarn", ("yarn",), ("--version",), "tool"),
    ToolSpec("bun", ("bun",), ("--version",), "runtime"),
    ToolSpec("deno", ("deno",), ("--version",), "runtime"),
    ToolSpec("java", ("java",), ("-version",), "runtime", r'version "(\d[\w._\-]*)"'),
    ToolSpec("javac", ("javac",), ("-version",), "compiler", r"javac (\d[\w._\-]*)"),
    ToolSpec("dotnet", ("dotnet",), ("--version",), "runtime"),
    ToolSpec("go", ("go",), ("version",), "runtime", r"go version go(\d[\w.\-+]*)"),
    ToolSpec("rustc", ("rustc",), ("--version",), "compiler", r"rustc (\d[\w.\-+]*)"),
    ToolSpec("cargo", ("cargo",), ("--version",), "tool", r"cargo (\d[\w.\-+]*)"),
    ToolSpec("php", ("php",), ("--version",), "runtime", r"PHP (\d[\w.\-+]*)"),
    ToolSpec("ruby", ("ruby",), ("--version",), "runtime", r"ruby (\d[\w.\-+]*)"),
    ToolSpec("perl", ("perl",), ("--version",), "runtime", r"\(v(\d[\w.\-+]*)\)"),
    # --- build systems -----------------------------------------------------
    ToolSpec("cmake", ("cmake",), ("--version",), "tool", r"cmake version (\d[\w.\-+]*)"),
    ToolSpec("ninja", ("ninja",), ("--version",), "tool"),
    ToolSpec("make", ("make",), ("--version",), "tool", r"GNU Make (\d[\w.\-+]*)"),
    ToolSpec("bazel", ("bazel", "bazelisk"), ("--version",), "tool"),
    # --- containers ---------------------------------------------------------
    ToolSpec("docker", ("docker",), ("--version",), "container", r"Docker version (\d[\w.\-+]*)"),
    ToolSpec("podman", ("podman",), ("--version",), "container", r"podman version (\d[\w.\-+]*)"),
    ToolSpec(
        "kubectl",
        ("kubectl",),
        ("version", "--client"),
        "container",
        r"v?Client Version.*?v(\d[\w.\-+]*)",
    ),
    ToolSpec("helm", ("helm",), ("version", "--short"), "container"),
    ToolSpec("terraform", ("terraform",), ("--version",), "tool", r"Terraform v(\d[\w.\-+]*)"),
    # --- cloud CLIs ----------------------------------------------------------
    ToolSpec("aws", ("aws",), ("--version",), "cloud", r"aws-cli/(\d[\w.\-+]*)"),
    ToolSpec("az", ("az",), ("--version",), "cloud", r"azure-cli\s+(\d[\w.\-+]*)"),
    ToolSpec("gcloud", ("gcloud",), ("--version",), "cloud", r"Google Cloud SDK (\d[\w.\-+]*)"),
    # --- package managers ------------------------------------------------------
    ToolSpec("pip", ("pip", "pip3"), ("--version",), "pkg-manager", r"pip (\d[\w.\-+]*)"),
    ToolSpec("uv", ("uv",), ("--version",), "pkg-manager", r"uv (\d[\w.\-+]*)"),
    ToolSpec("poetry", ("poetry",), ("--version",), "pkg-manager"),
    ToolSpec("conda", ("conda",), ("--version",), "pkg-manager", r"conda (\d[\w.\-+]*)"),
    ToolSpec("choco", ("choco",), ("--version",), "pkg-manager", r"(\d[\w.\-+]*)"),
    ToolSpec("winget", ("winget",), ("--version",), "pkg-manager", r"v(\d[\w.\-+]*)"),
    ToolSpec("scoop", ("scoop",), ("--version",), "pkg-manager"),
    ToolSpec("brew", ("brew",), ("--version",), "pkg-manager", r"Homebrew (\d[\w.\-+]*)"),
    ToolSpec("apt", ("apt",), ("--version",), "pkg-manager", r"apt (\d[\w.\-+]*)"),
    ToolSpec("dnf", ("dnf",), ("--version",), "pkg-manager", r"(\d[\w.\-+]*)"),
    ToolSpec("pacman", ("pacman",), ("--version",), "pkg-manager", r"Pacman v(\d[\w.\-+]*)"),
)

COMPILER_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("gcc", ("gcc",), ("--version",), "compiler", r"gcc[^\d]*(\d[\w.\-+]*)"),
    ToolSpec("clang", ("clang",), ("--version",), "compiler", r"[Cc]lang version (\d[\w.\-+]*)"),
    ToolSpec("cl", ("cl",), ("",), "compiler"),  # MSVC prints banner w/o args
)


def _install_source(path: str) -> str:
    """Best-effort installation-source heuristic from the exe path."""
    p = path.lower().replace(os.sep, "/")
    markers = [
        ("windowsapps", "store-alias"),
        ("/pyenv/", "pyenv"),
        ("/.pyenv/", "pyenv"),
        ("/nvm/", "nvm"),
        ("/.nvm/", "nvm"),
        ("/fnm_", "fnm"),
        ("/volta/", "volta"),
        ("/mise/", "mise"),
        ("/asdf/", "asdf"),
        ("/conda", "conda"),
        ("/miniconda", "conda"),
        ("/anaconda", "conda"),
        ("/.cargo/bin", "rustup"),
        ("/scoop/", "scoop"),
        ("/chocolatey/", "choco"),
        ("/homebrew/", "brew"),
        ("/cellar/", "brew"),
        ("/usr/local/bin", "system-local"),
        ("/usr/bin", "distro"),
        ("/microsoft visual studio", "vs-installer"),
        ("/nodejs", "official-installer"),
        ("/python3", "official-installer"),
        ("/python", "official-installer"),
        ("/dotnet", "official-installer"),
        ("/go/bin", "official-installer"),
        ("/docker", "docker-desktop"),
    ]
    for marker, source in markers:
        if marker in p:
            return source
    return "unknown"


def _run_version(runner: CommandRunner, exe: str, spec: ToolSpec) -> tuple[str | None, str]:
    argv = (exe, *spec.version_args) if spec.version_args != ("",) else (exe,)
    res = runner.run(argv, timeout=15.0)
    output = res.stdout or res.stderr
    if not res.ok and not output.strip():
        return None, ""
    if spec.version_regex:
        m = re.search(spec.version_regex, output)
        return (m.group(1) if m else None), output[:500]
    return extract_version(output) or None, output[:500]


def detect_toolchain(
    runner: CommandRunner,
    *,
    path_env: str | None = None,
    specs: tuple[ToolSpec, ...] = TOOL_SPECS,
) -> list[ToolInstallation]:
    """Resolve every tool spec against PATH. Returns all installations,
    including duplicates of the same tool at different paths.
    """
    # Resolving PATH is filesystem work and stays sequential; asking each
    # executable for its version is a subprocess, and there are dozens.
    planned: list[tuple[ToolSpec, str, int, int]] = []
    for spec in specs:
        for cmd in spec.commands:
            matches = resolve_all_on_path(cmd, path_env=path_env)
            for precedence, exe in enumerate(matches):
                planned.append((spec, exe, precedence, len(matches)))

    if not planned:
        return []

    # Independent, I/O-bound, and the GIL is released around subprocess.run.
    # Bounded because a machine with many toolchains should not open sixty
    # processes at once.
    versions: list[str | None] = [None] * len(planned)
    with ThreadPoolExecutor(max_workers=min(12, len(planned))) as pool:
        futures = {
            pool.submit(_run_version, runner, exe, spec): index
            for index, (spec, exe, _precedence, _total) in enumerate(planned)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                versions[index] = future.result()[0]
            except Exception:
                versions[index] = None

    # Rebuilt in the original order: `precedence` and `is_active` come from it,
    # so a reordered result would change which installation is called active.
    return [
        ToolInstallation(
            name=spec.name,
            version=versions[index],
            exe_path=exe,
            install_source=_install_source(exe),
            is_active=precedence == 0,
            precedence=precedence if total > 1 else None,
        )
        for index, (spec, exe, precedence, total) in enumerate(planned)
    ]


def find_duplicates(installs: list[ToolInstallation]) -> dict[str, list[ToolInstallation]]:
    """Group installations by tool name where more than one exists."""
    by_name: dict[str, list[ToolInstallation]] = {}
    for inst in installs:
        by_name.setdefault(inst.name, []).append(inst)
    return {k: v for k, v in by_name.items() if len(v) > 1}


class ToolchainProbe(Probe):
    id = "toolchain/detect"
    version = "1"
    dependencies = ()

    def _shim_findings(
        self, dups: dict[str, list[ToolInstallation]], path_env: str
    ) -> list[Finding]:
        """Version managers that are installed but not in the resolution path.

        A manager reporting the right version while every command resolves
        somewhere else is invisible from inside the manager: `pyenv version`
        and `python --version` disagree, and neither one is wrong about what it
        was asked.
        """
        from devrepro.platforms.shims import analyse_shims

        resolutions = {
            name: [i.exe_path for i in group if i.exe_path] for name, group in dups.items()
        }
        analysis = analyse_shims(path_env, resolutions, platform=self.ctx.platform)

        findings: list[Finding] = []
        for shadow in analysis.shadowed:
            findings.append(
                self.finding(
                    f"{shadow.tool}/shim-bypassed",
                    FindingState.WARN,
                    f"{shadow.manager} manages {shadow.tool!r}, but another "
                    f"installation resolves first.",
                    evidence=(
                        Evidence(
                            source="env",
                            excerpt=shadow.summary,
                        ),
                    ),
                    detected=shadow.winning_path,
                    required=shadow.shim_path,
                    component=shadow.tool,
                    remediation_hint=(
                        f"Move the {shadow.manager} shim directory earlier in PATH "
                        f"than {shadow.winning_path}. Until then the version "
                        f"{shadow.manager} reports is not the one commands get, and "
                        "the project's pin is not being honoured."
                    ),
                )
            )
        return findings

    def run(self) -> ProbeResult:
        path_env = self.ctx.env.get("PATH")
        installs = detect_toolchain(self.ctx.runner, path_env=path_env)
        dups = find_duplicates(installs)

        findings = []
        findings.extend(self._shim_findings(dups, path_env or ""))
        ev_dup = Evidence(
            source="command",
            command=(
                ("where.exe", "<tool>")
                if self.ctx.platform == "windows"
                else ("which", "-a", "<tool>")
            ),
            excerpt="multiple installations resolved across PATH",
        )
        for name, group in sorted(dups.items()):
            versions = sorted({i.version or "?" for i in group})
            findings.append(
                self.finding(
                    f"{name}/multiple-installations",
                    FindingState.WARN if len(versions) > 1 else FindingState.INFO,
                    f"{len(group)} installations of '{name}' found"
                    + (
                        f" with differing versions: {', '.join(versions)}"
                        if len(versions) > 1
                        else ""
                    ),
                    evidence=(ev_dup,),
                    detected=", ".join(versions),
                    component=name,
                    remediation_hint="Keep the installation your shell actually resolves first; "
                    "remove or de-prefer the rest (plan available via `devrepro plan`).",
                )
            )

        # Windows Store python alias warning
        if self.ctx.platform == "windows":
            py_installs = [i for i in installs if i.name == "python"]
            aliases = [i for i in py_installs if i.install_source == "store-alias"]
            real = [i for i in py_installs if i.install_source != "store-alias"]
            if aliases and real:
                findings.append(
                    self.finding(
                        "python/store-alias-shadow",
                        FindingState.WARN,
                        "A Windows Store python alias shadows a real Python installation.",
                        evidence=(
                            Evidence(
                                source="command",
                                command=("where", "python"),
                                excerpt="WindowsApps alias precedes real install",
                            ),
                        ),
                        detected=aliases[0].exe_path,
                        component="python",
                        remediation_hint="Disable App execution aliases for python.exe "
                        "(Settings > Apps > Advanced app settings). SAFE to toggle.",
                    )
                )

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={"tools": [t.model_dump(mode="json") for t in installs]},
        )
