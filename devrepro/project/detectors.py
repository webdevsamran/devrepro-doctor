"""Project requirement detectors.

Parse manifests/lockfiles and infer ONLY requirements the project actually
declares. Never invent exact versions: specs are stored verbatim as the
project declared them (ranges, carets, wildcards).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from devrepro.core.errors import ProjectParseError
from devrepro.core.models import ProjectRequirement, RequirementKind

__all__ = ["ProjectDetector", "detect_project_kind", "detect_requirements"]


def _read(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _req(
    ecosystem: str,
    name: str,
    spec: str,
    kind: RequirementKind,
    source: Path,
    *,
    optional: bool = False,
    note: str | None = None,
) -> ProjectRequirement:
    return ProjectRequirement(
        ecosystem=ecosystem,
        name=name,
        spec=spec if spec else "*",
        kind=kind,
        source_file=str(source),
        optional=optional,
        note=note,
    )


# ---------------------------------------------------------------- python --


def _python_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    pyproject = root / "pyproject.toml"
    text = _read(pyproject)
    if text is not None:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ProjectParseError(f"invalid pyproject.toml: {exc}") from exc
        project = data.get("project", {})
        rp = project.get("requires-python")
        if isinstance(rp, str):
            out.append(_req("python", "python", rp, RequirementKind.RUNTIME, pyproject))
        for dep in project.get("dependencies", []) or []:
            name, _, spec = _pep508_split(str(dep))
            out.append(_req("python", name, spec or "*", RequirementKind.RUNTIME, pyproject))
        tool_poetry = data.get("tool", {}).get("poetry", {})
        for dep_name, dep_spec in (tool_poetry.get("dependencies") or {}).items():
            if dep_name == "python":
                continue
            spec = dep_spec if isinstance(dep_spec, str) else "*"
            out.append(
                _req("python", dep_name, spec.lstrip("^~"), RequirementKind.RUNTIME, pyproject)
            )
    for reqfile in sorted(root.glob("requirements*.txt")):
        txt = _read(reqfile) or ""
        for raw_line in txt.splitlines():
            entry = raw_line.strip()
            if not entry or entry.startswith(("#", "-")):
                continue
            name, _, spec = _pep508_split(entry)
            out.append(_req("python", name, spec or "*", RequirementKind.RUNTIME, reqfile))
    return out


def _pep508_split(dep: str) -> tuple[str, str, str]:
    m = re.match(r"^([A-Za-z0-9._\-]+)\s*(\[[^\]]*\])?\s*(.*)$", dep.strip())
    if not m:
        return dep.strip(), "", ""
    return m.group(1), m.group(2) or "", m.group(3).strip()


def _lockfiles(root: Path) -> list[ProjectRequirement]:
    """Lockfile presence is itself a reproducibility signal."""
    out: list[ProjectRequirement] = []
    markers = [
        ("poetry.lock", "python", "poetry-lock"),
        ("uv.lock", "python", "uv-lock"),
        ("Pipfile.lock", "python", "pipenv-lock"),
        ("package-lock.json", "node", "npm-lock"),
        ("pnpm-lock.yaml", "node", "pnpm-lock"),
        ("yarn.lock", "node", "yarn-lock"),
        ("bun.lockb", "node", "bun-lock"),
        ("go.sum", "go", "go-sum"),
        ("Cargo.lock", "rust", "cargo-lock"),
        ("composer.lock", "php", "composer-lock"),
        ("Gemfile.lock", "ruby", "bundler-lock"),
        ("poetry.toml", "python", "poetry-config"),
    ]
    for fname, eco, label in markers:
        p = root / fname
        if p.is_file():
            out.append(_req(eco, label, "*", RequirementKind.TOOL, p, note="lockfile present"))
    return out


# ------------------------------------------------------------------ node --


def _node_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    pkg = root / "package.json"
    text = _read(pkg)
    if text is not None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectParseError(f"invalid package.json: {exc}") from exc
        engines = data.get("engines") or {}
        node_spec = engines.get("node")
        if isinstance(node_spec, str):
            out.append(_req("node", "node", node_spec, RequirementKind.RUNTIME, pkg))
        npm_spec = engines.get("npm")
        if isinstance(npm_spec, str):
            out.append(_req("node", "npm", npm_spec, RequirementKind.RUNTIME, pkg))
        for section in ("dependencies", "devDependencies"):
            for name, spec in (data.get(section) or {}).items():
                out.append(
                    _req(
                        "node",
                        name,
                        str(spec),
                        RequirementKind.RUNTIME,
                        pkg,
                        optional=(section == "devDependencies"),
                    )
                )
    for marker in (".nvmrc", ".node-version"):
        p = root / marker
        t = _read(p)
        if t and t.strip():
            out.append(_req("node", "node", t.strip().lstrip("v"), RequirementKind.RUNTIME, p))
    return out


# ------------------------------------------------------------- runtimes ---


def _dotnet_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    gj = root / "global.json"
    text = _read(gj)
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectParseError(f"invalid global.json: {exc}") from exc
        sdk = (data.get("sdk") or {}).get("version")
        if isinstance(sdk, str):
            out.append(_req("dotnet", "dotnet-sdk", sdk, RequirementKind.RUNTIME, gj))
    for csproj in list(root.glob("*.csproj"))[:10]:
        t = _read(csproj) or ""
        for fw in re.findall(r"<TargetFramework>([^<]+)</TargetFramework>", t):
            out.append(
                _req("dotnet", "target-framework", fw.strip(), RequirementKind.RUNTIME, csproj)
            )
    return out


def _go_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    gomod = root / "go.mod"
    text = _read(gomod)
    if text:
        m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", text, re.MULTILINE)
        if m:
            out.append(_req("go", "go", ">=" + m.group(1), RequirementKind.RUNTIME, gomod))
    return out


def _rust_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    rt = root / "rust-toolchain.toml"
    text = _read(rt)
    if text:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ProjectParseError(f"invalid rust-toolchain.toml: {exc}") from exc
        channel = data.get("toolchain", {}).get("channel")
        if isinstance(channel, str):
            out.append(_req("rust", "rust-toolchain", channel, RequirementKind.RUNTIME, rt))
    else:
        rt2 = root / "rust-toolchain"
        t = _read(rt2)
        if t and t.strip():
            out.append(_req("rust", "rust-toolchain", t.strip(), RequirementKind.RUNTIME, rt2))
    cargo = root / "Cargo.toml"
    ctext = _read(cargo)
    if ctext:
        m = re.search(r"rust-version\s*=\s*(.+)", ctext)
        if m:
            ver = m.group(1).strip().strip(chr(34)).strip(chr(39))
            out.append(_req("rust", "rustc", ver, RequirementKind.RUNTIME, cargo))
    return out


def _php_ruby_java_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    composer = root / "composer.json"
    text = _read(composer)
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectParseError(f"invalid composer.json: {exc}") from exc
        php_spec = (data.get("require") or {}).get("php")
        if isinstance(php_spec, str):
            out.append(_req("php", "php", php_spec, RequirementKind.RUNTIME, composer))
    ruby_version = root / ".ruby-version"
    t = _read(ruby_version)
    if t and t.strip():
        out.append(_req("ruby", "ruby", t.strip(), RequirementKind.RUNTIME, ruby_version))
    java_version = root / ".java-version"
    t = _read(java_version)
    if t and t.strip():
        out.append(_req("java", "java", t.strip(), RequirementKind.RUNTIME, java_version))
    # .tool-versions / mise.toml cover many ecosystems at once
    tv = root / ".tool-versions"
    t = _read(tv)
    if t:
        for line in t.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                out.append(
                    _req("generic", f"tool-versions:{parts[0]}", parts[1], RequirementKind.TOOL, tv)
                )
    mise = root / "mise.toml"
    t = _read(mise)
    if t:
        for line in t.splitlines():
            m = re.match(r"^\s*([\w-]+)\s*=\s*(.+)$", line)
            if m:
                out.append(
                    _req(
                        "generic",
                        f"mise:{m.group(1)}",
                        m.group(2).strip(chr(34)).strip(chr(39)),
                        RequirementKind.TOOL,
                        mise,
                    )
                )
    return out


# ------------------------------------------------------------------- c/c++


def _cpp_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    cmake_lists = root / "CMakeLists.txt"
    text = _read(cmake_lists)
    if text:
        m = re.search(r"cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)", text)
        if m:
            out.append(
                _req("cpp", "cmake", ">=" + m.group(1), RequirementKind.COMPILER, cmake_lists)
            )
    vcpkg = root / "vcpkg.json"
    if vcpkg.is_file():
        out.append(_req("cpp", "vcpkg-manifest", "*", RequirementKind.TOOL, vcpkg))
    conan = root / "conanfile.txt"
    if conan.is_file():
        out.append(_req("cpp", "conan", "*", RequirementKind.TOOL, conan))
    return out


# ------------------------------------------------------------- containers -


def _container_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    dockerfile = root / "Dockerfile"
    if dockerfile.is_file():
        out.append(_req("container", "docker-build", "*", RequirementKind.CONTAINER, dockerfile))
    for compose in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"):
        p = root / compose
        if p.is_file():
            out.append(_req("container", "docker-compose", "*", RequirementKind.CONTAINER, p))
            break
    devc = root / ".devcontainer" / "devcontainer.json"
    if devc.is_file():
        out.append(_req("container", "devcontainer", "*", RequirementKind.CONTAINER, devc))
    elif (root / ".devcontainer.json").is_file():
        out.append(
            _req(
                "container",
                "devcontainer",
                "*",
                RequirementKind.CONTAINER,
                root / ".devcontainer.json",
            )
        )
    return out


# --------------------------------------------------------------------- CI -

_CI_VERSION_RE = {
    "python": re.compile(r"python-version:\s*(\S+)"),
    "node": re.compile(r"node-version:\s*(\S+)"),
    "go": re.compile(r"go-version:\s*(\S+)"),
}


def _ci_deps(root: Path) -> list[ProjectRequirement]:
    out: list[ProjectRequirement] = []
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return out
    for wf in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        text = _read(wf)
        if not text:
            continue
        for eco, pattern in _CI_VERSION_RE.items():
            for m in pattern.finditer(text):
                ver = m.group(1).strip()
                if ver and ver != "$":
                    out.append(_req(eco, f"ci:{eco}", ver, RequirementKind.RUNTIME, wf))
                    break
    return out


# ------------------------------------------------------------------ main --


class ProjectDetector:
    """Plugin API v1: subclass and add to ``detect_requirements`` chain."""

    name: str = "base"

    def detect(self, root: Path) -> list[ProjectRequirement]:  # pragma: no cover
        return []


_BUILTIN_DETECTORS = (
    _python_deps,
    _node_deps,
    _dotnet_deps,
    _go_deps,
    _rust_deps,
    _php_ruby_java_deps,
    _cpp_deps,
)


def detect_requirements(root: Path | str) -> list[ProjectRequirement]:
    """Run all built-in detectors against a project directory."""
    root = Path(root)
    out: list[ProjectRequirement] = []
    for detector in _BUILTIN_DETECTORS:
        try:
            out.extend(detector(root))
        except ProjectParseError:
            raise
        except Exception as exc:
            out.append(
                ProjectRequirement(
                    ecosystem="generic",
                    name=f"parse-error:{detector.__name__}",
                    spec="*",
                    kind=RequirementKind.TOOL,
                    source_file=str(root),
                    note=f"detector failed: {type(exc).__name__}: {exc}",
                )
            )
    out.extend(_lockfiles(root))
    out.extend(_container_deps(root))
    out.extend(_ci_deps(root))
    return out


def detect_project_kind(root: Path) -> list[str]:
    """Coarse ecosystem labels used to select rule packs."""
    kinds: list[str] = []
    checks = [
        ("python", ("pyproject.toml", "requirements.txt", "*.py")),
        ("node", ("package.json",)),
        ("dotnet", ("global.json", "*.csproj", "*.sln")),
        ("go", ("go.mod",)),
        ("rust", ("Cargo.toml",)),
        ("php", ("composer.json",)),
        ("ruby", ("Gemfile",)),
        ("java", ("pom.xml", "build.gradle", "build.gradle.kts")),
        ("cpp", ("CMakeLists.txt", "Makefile")),
        ("containers", ("Dockerfile", "compose.yaml", "docker-compose.yml")),
    ]
    for kind, markers in checks:
        for marker in markers:
            if any(root.glob(marker)):
                kinds.append(kind)
                break
    return kinds
