"""Monorepo-aware project discovery and ecosystem inventory.

Capabilities:
- workspace-root detection (npm/yarn/pnpm workspaces, Cargo workspaces,
  go.work, Nx/Turbo/Bazel markers);
- nested-project enumeration with independently versioned toolchains;
- parent/child runtime-version conflict detection;
- repository language inventory from manifests plus source evidence;
- lockfile coverage analysis per ecosystem.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "LanguageInventory",
    "LockfileCoverage",
    "MonorepoReport",
    "NestedConflict",
    "ProjectNode",
    "analyze_monorepo",
]

# manifest filename -> ecosystem
_MANIFESTS: dict[str, str] = {
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "composer.json": "php",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "*.csproj": "dotnet",
}

# ecosystem -> lockfiles that pin dependency resolution
_LOCKFILES: dict[str, tuple[str, ...]] = {
    "node": ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"),
    "python": ("poetry.lock", "uv.lock", "Pipfile.lock", "pdm.lock", "conda-lock.yml"),
    "rust": ("Cargo.lock",),
    "go": ("go.sum",),
    "php": ("composer.lock",),
    "ruby": ("Gemfile.lock",),
    "java": (),  # Maven/Gradle resolve at build time; no universal lockfile
    "dotnet": ("packages.lock.json",),
}

_WORKSPACE_MARKERS = (
    "pnpm-workspace.yaml",
    "nx.json",
    "turbo.json",
    "lerna.json",
    "go.work",
    "WORKSPACE",  # Bazel
    "MODULE.bazel",
)

_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "target",
    "dist",
    "build",
    ".tox",
}


@dataclass(frozen=True)
class ProjectNode:
    """One discovered project root inside the repository."""

    path: str  # repo-relative, POSIX separators
    ecosystem: str
    depth: int


@dataclass(frozen=True)
class NestedConflict:
    """Parent and child demand incompatible versions of the same runtime."""

    tool: str
    parent_path: str
    parent_spec: str
    child_path: str
    child_spec: str
    detail: str


@dataclass(frozen=True)
class LanguageInventory:
    """Language evidence: manifest-declared plus source-file signals."""

    languages: dict[str, int] = field(default_factory=dict)  # lang -> file count
    manifest_languages: tuple[str, ...] = ()
    source_evidence_languages: tuple[str, ...] = ()

    def primary(self) -> str | None:
        if not self.languages:
            return None
        return max(self.languages.items(), key=lambda kv: kv[1])[0]


@dataclass(frozen=True)
class LockfileCoverage:
    """Which ecosystems declare dependencies but lack a lockfile."""

    covered: tuple[str, ...] = ()
    uncovered: tuple[str, ...] = ()
    not_applicable: tuple[str, ...] = ()  # ecosystems without lock semantics


@dataclass(frozen=True)
class MonorepoReport:
    root: str
    is_monorepo: bool
    workspace_markers: tuple[str, ...]
    projects: tuple[ProjectNode, ...]
    conflicts: tuple[NestedConflict, ...]
    inventory: LanguageInventory
    lockfiles: LockfileCoverage


def _read_json(path: Path) -> dict[str, object]:
    try:
        data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def _read_toml(path: Path) -> dict[str, object]:
    try:
        data: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _declared_versions(manifest: Path, ecosystem: str) -> dict[str, str]:
    """Extract declared runtime/tool version constraints from a manifest."""
    out: dict[str, str] = {}
    if ecosystem == "node":
        data = _read_json(manifest)
        engines = data.get("engines")
        if isinstance(engines, dict):
            for k in ("node", "npm", "pnpm", "yarn"):
                v = engines.get(k)
                if isinstance(v, str):
                    out[k] = v
    elif ecosystem == "python":
        data = _read_toml(manifest)
        proj = data.get("project")
        if isinstance(proj, dict):
            req_python = proj.get("requires-python")
            if isinstance(req_python, str):
                out["python"] = req_python
    elif ecosystem == "dotnet":
        text = manifest.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", text)
        if m:
            out["dotnet"] = m.group(1).strip()
    elif ecosystem == "go":
        data = _read_toml(manifest)  # go.mod is TOML-ish only for toolchain line
        # go.mod is not TOML; parse the go/toolchain directives directly
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError:
            text = ""
        m = re.search(r"^toolchain\s+(\S+)", text, re.MULTILINE)
        g = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
        if m:
            out["go"] = m.group(1)
        elif g:
            out["go"] = g.group(1)
    return out


def _walk(root: Path) -> list[tuple[str, list[str], list[str]]]:
    """os.walk wrapper that prunes skip dirs and yields repo-relative dirs."""
    out: list[tuple[str, list[str], list[str]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        rel = Path(dirpath).relative_to(root).as_posix()
        out.append((rel, dirnames, filenames))
    return out


def _discover_projects(root: Path) -> tuple[list[ProjectNode], list[tuple[Path, str]]]:
    """Walk the tree collecting project nodes and their manifest paths."""
    projects: list[ProjectNode] = []
    manifests: list[tuple[Path, str]] = []
    for rel, _dirnames, filenames in _walk(root):
        depth = 0 if rel == "." else rel.count("/") + 1
        for fname in filenames:
            eco = _MANIFESTS.get(fname)
            if eco is None and fname.endswith(".csproj"):
                eco = "dotnet"
            if eco:
                p = root / rel / fname if rel != "." else root / fname
                manifests.append((p, eco))
                node_path = rel if rel != "." else "."
                projects.append(ProjectNode(path=node_path, ecosystem=eco, depth=depth))
    return projects, manifests


def _detect_conflicts(root: Path, manifests: list[tuple[Path, str]]) -> list[NestedConflict]:
    by_tool: dict[str, list[tuple[str, str, str]]] = {}
    for path, eco in manifests:
        # use the project DIRECTORY (not manifest filename) for nesting checks
        rel = path.parent.relative_to(root).as_posix()
        for tool, spec in _declared_versions(path, eco).items():
            by_tool.setdefault(tool, []).append((rel, spec, path.parent.name))
    conflicts: list[NestedConflict] = []
    from devrepro.core.versioning import parse_spec

    for tool, entries in by_tool.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a_rel, a_spec, _ = entries[i]
                b_rel, b_spec, _ = entries[j]
                # only compare ancestor/descendant pairs (nested projects)
                nested = (
                    a_rel == "."
                    or b_rel == "."
                    or a_rel.startswith(b_rel + "/")
                    or b_rel.startswith(a_rel + "/")
                )
                if not nested:
                    continue
                try:
                    ra = parse_spec(a_spec)
                    rb = parse_spec(b_spec)
                except Exception:
                    conflicts.append(
                        NestedConflict(
                            tool=tool,
                            parent_path=a_rel,
                            parent_spec=a_spec,
                            child_path=b_rel,
                            child_spec=b_spec,
                            detail="version specs could not be compared automatically",
                        )
                    )
                    continue
                # incompatible when no sampled version satisfies both ranges
                if not _ranges_overlap(ra, rb):
                    conflicts.append(
                        NestedConflict(
                            tool=tool,
                            parent_path=a_rel,
                            parent_spec=a_spec,
                            child_path=b_rel,
                            child_spec=b_spec,
                            detail="no version satisfies both parent and child constraints",
                        )
                    )
    return conflicts


def _ranges_overlap(a: object, b: object) -> bool:
    """Approximate range-overlap check by sampling candidate versions."""
    from devrepro.core.versioning import parse_version

    candidates = [
        "0.0.1",
        "3.0.0",
        "6.0.0",
        "8.0.0",
        "10.0.0",
        "12.0.0",
        "14.0.0",
        "16.0.0",
        "18.0.0",
        "20.0.0",
        "21.0.0",
        "22.0.0",
        "24.0.0",
    ]
    for c in candidates:
        try:
            v = parse_version(c)
            if a.satisfied_by(v) and b.satisfied_by(v):  # type: ignore[attr-defined]
                return True
        except Exception:
            continue
    return False


def _language_inventory(root: Path, manifest_langs: set[str]) -> LanguageInventory:
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
        ".java": "java",
        ".kt": "kotlin",
        ".cs": "csharp",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".hpp": "cpp",
        ".swift": "swift",
        ".sql": "sql",
        ".sh": "shell",
        ".ps1": "powershell",
    }
    counts: dict[str, int] = {}
    for _rel, dirnames, filenames in _walk(root):
        del dirnames
        for f in filenames:
            lang = ext_map.get(Path(f).suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    source_evidence = tuple(sorted(counts))
    return LanguageInventory(
        languages=counts,
        manifest_languages=tuple(sorted(manifest_langs)),
        source_evidence_languages=source_evidence,
    )


def _lockfile_coverage(root: Path, manifest_langs: set[str]) -> LockfileCoverage:
    present_locks: set[str] = set()
    for _rel, dirnames, filenames in _walk(root):
        del dirnames
        for f in filenames:
            for eco, locks in _LOCKFILES.items():
                if f in locks:
                    present_locks.add(eco)
    covered = tuple(sorted(manifest_langs & present_locks))
    uncovered = tuple(sorted(eco for eco in manifest_langs - present_locks if _LOCKFILES.get(eco)))
    not_applicable = tuple(sorted(eco for eco in manifest_langs if not _LOCKFILES.get(eco)))
    return LockfileCoverage(covered=covered, uncovered=uncovered, not_applicable=not_applicable)


def analyze_monorepo(root: Path | str) -> MonorepoReport:
    """Analyze a repository for multi-project structure and consistency."""
    root = Path(root).resolve()
    markers = tuple(m for m in _WORKSPACE_MARKERS if (root / m).exists())
    npm_pkg = _read_json(root / "package.json")
    ws_field = npm_pkg.get("workspaces")
    has_npm_ws = bool(ws_field)
    cargo_ws = "workspace" in _read_toml(root / "Cargo.toml")
    is_monorepo = bool(markers or has_npm_ws or cargo_ws)
    projects, manifests = _discover_projects(root)
    conflicts = _detect_conflicts(root, manifests)
    manifest_langs = {eco for _, eco in manifests}
    inventory = _language_inventory(root, manifest_langs)
    lockfiles = _lockfile_coverage(root, manifest_langs)
    return MonorepoReport(
        root=str(root),
        is_monorepo=is_monorepo,
        workspace_markers=markers
        + (("package.json#workspaces",) if has_npm_ws else ())
        + (("Cargo.toml#[workspace]",) if cargo_ws else ()),
        projects=tuple(projects),
        conflicts=tuple(conflicts),
        inventory=inventory,
        lockfiles=lockfiles,
    )
