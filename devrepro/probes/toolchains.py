"""Toolchain detection: a declarative table of developer tools, resolved
against PATH with version extraction and best-effort install-source
heuristics. Duplicate installations are reported, never hidden.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from devrepro.core.models import Evidence, FindingState, ToolInstallation
from devrepro.core.runner import CommandRunner
from devrepro.probes.base import Probe, ProbeResult
from devrepro.probes.helpers import extract_version, resolve_all_on_path

__all__ = ["ToolSpec", "TOOL_SPECS", "detect_toolchain", "ToolchainProbe", "COMPILER_SPECS"]


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
    ToolSpec("python", ("python", "python3"), ("--version",), "runtime", r"[Pp]ython (\d[\w.\-+]*)"),
    ToolSpec("node", ("node",), ("--version",), "runtime", r"v(\d[\w.\-+]*)"),
    ToolSpec("npm", ("npm",), ("--version",), "tool"),
    ToolSpec("pnpm", ("pnpm",), ("--version",), "tool"),
    ToolSpec("yarn", ("yarn",), ("--version",), "tool"),
    ToolSpec("bun", ("bun",), ("--version",), "runtime"),
    ToolSpec("deno", ("deno",), ("--version",), "runtime"),
    ToolSpec("java", ("java",), ("-version",), "runtime", r'version "(\d[\w._\-]*)"'),
    ToolSpec("javac", ("javac",), ("-version",), "compiler", r'javac (\d[\w._\-]*)'),
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
    ToolSpec("kubectl", ("kubectl",), ("version", "--client"), "container", r"v?Client Version.*?v(\d[\w.\-+]*)"),
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


def _run_version(
    runner: CommandRunner, exe: str, spec: ToolSpec
) -> tuple[str | None, str]:
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
    including duplicates of the same tool at different paths."""
    installs: list[ToolInstallation] = []
    for spec in specs:
        for cmd in spec.commands:
            matches = resolve_all_on_path(cmd, path_env=path_env)
            for precedence, exe in enumerate(matches):
                version, _out = _run_version(runner, exe, spec)
                installs.append(
                    ToolInstallation(
                        name=spec.name,
                        version=version,
                        exe_path=exe,
                        install_source=_install_source(exe),
                        is_active=precedence == 0,
                        precedence=precedence if len(matches) > 1 else None,
                    )
                )
    return installs


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

    def run(self) -> ProbeResult:
        path_env = self.ctx.env.get("PATH")
        installs = detect_toolchain(self.ctx.runner, path_env=path_env)
        dups = find_duplicates(installs)

        findings = []
        ev_dup = Evidence(
            source="command",
            command=("where.exe <tool>" if self.ctx.platform == "windows" else "which -a <tool>"),
            excerpt="multiple installations resolved across PATH",
        )
        for name, group in sorted(dups.items()):
            versions = sorted({i.version or "?" for i in group})
            findings.append(
                self.finding(
                    f"{name}/multiple-installations",
                    FindingState.WARN if len(versions) > 1 else FindingState.INFO,
                    f"{len(group)} installations of '{name}' found"
                    + (f" with differing versions: {', '.join(versions)}" if len(versions) > 1 else ""),
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
                        evidence=(Evidence(source="command", command=("where", "python"),
                                           excerpt="WindowsApps alias precedes real install"),),
                        detected=aliases[0].exe_path,
                        component="python",
                        remediation_hint="Disable App execution aliases for python.exe "
                        "(Settings → Apps → Advanced app settings). SAFE to toggle.",
                    )
                )

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={"tools": [t.model_dump(mode="json") for t in installs]},
        )