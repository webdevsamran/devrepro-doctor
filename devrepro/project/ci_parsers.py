"""CI environment parsers and local-vs-CI diff.

Parses declared toolchains from GitHub Actions workflows, GitLab CI
configs and Azure Pipelines files, then diffs them against the local
machine's tool inventory to explain "CI passes, my machine fails" (or the
inverse). Parsing is text-based to avoid a YAML hard dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["CiToolchain", "collect_ci_toolchains", "local_vs_ci_diff"]


@dataclass(frozen=True)
class CiToolchain:
    """A toolchain version declared by CI configuration."""

    tool: str  # python | node | go | java | dotnet | ruby | php
    spec: str  # raw version or range as written
    source_file: str  # repo-relative path
    platform: str | None = None  # runs-on / image / vmImage hint


_TOOLS = {"python", "node", "go", "java", "dotnet", "ruby", "php"}

# actions that set up toolchains: action name -> tool
_SETUP_ACTIONS = {
    "actions/setup-python": "python",
    "actions/setup-node": "node",
    "actions/setup-go": "go",
    "actions/setup-java": "java",
    "actions/setup-dotnet": "dotnet",
    "actions/setup-ruby": "ruby",
    "actions/setup-php": "php",
}

_QUOTE = ("'", '"')


def _gha_workflows(root: Path) -> list[Path]:
    d = root / ".github" / "workflows"
    if not d.is_dir():
        return []
    return sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))


def _unquote(v: str) -> str:
    return v.strip("".join(_QUOTE)).strip()


def _parse_github_actions(path: Path, root: Path) -> list[CiToolchain]:
    out: list[CiToolchain] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rel = path.relative_to(root).as_posix()
    current_action: str | None = None
    current_indent = 0
    runs_on: str | None = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        m_act = re.match(r"-?\s*uses:\s*([\w.-]+/[\w.-]+)", stripped)
        if m_act:
            current_action = m_act.group(1)
            current_indent = indent
            continue
        if current_action and indent > current_indent:
            m_with = re.match(r"([\w-]+)-version:\s*(.+?)\s*(?:#.*)?$", stripped)
            if m_with and m_with.group(1) in _TOOLS:
                spec = _unquote(m_with.group(2))
                # workflow-expression templates (e.g. ${{ matrix.python-version }})
                # are not concrete pins; normalize to wildcard
                if "${{" in spec:
                    spec = "*"
                out.append(CiToolchain(m_with.group(1), spec, rel, runs_on))
            elif current_action in _SETUP_ACTIONS and stripped.startswith("version:"):
                v = _unquote(stripped.split(":", 1)[1])
                if v:
                    out.append(CiToolchain(_SETUP_ACTIONS[current_action], v, rel, runs_on))
        if indent <= current_indent:
            current_action = None
        m_run = re.match(r"runs-on:\s*(.+?)\s*$", stripped)
        if m_run:
            runs_on = _unquote(m_run.group(1))
    return out


def _tool_from_image(image: str) -> tuple[str, str] | None:
    """Map a container image like python:3.12-bookworm to (tool, tag)."""
    base = image.split("/", 1)[-1]
    name = base.split(":", 1)[0].split("-", 1)[0]
    if name in _TOOLS:
        tag = base.split(":", 1)[1] if ":" in base else "*"
        return name, tag
    return None


def _parse_gitlab_ci(path: Path, root: Path) -> list[CiToolchain]:
    out: list[CiToolchain] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rel = path.relative_to(root).as_posix()
    for line in lines:
        stripped = line.strip()
        m = re.match(r"(?:image|name):\s*(.+?)\s*$", stripped)
        if not m:
            continue
        image = _unquote(m.group(1))
        hit = _tool_from_image(image)
        if hit:
            tool, tag = hit
            out.append(CiToolchain(tool, tag, rel, image))
    return out


def _parse_azure_pipelines(path: Path, root: Path) -> list[CiToolchain]:
    out: list[CiToolchain] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel = path.relative_to(root).as_posix()
    vm = re.search(r"^vmImage:\s*(.+?)\s*$", text, re.MULTILINE)
    platform = _unquote(vm.group(1)) if vm else None
    task_map = {
        "UsePythonVersion": "python",
        "UseNode": "node",
        "UseGo": "go",
        "UseDotNet": "dotnet",
        "JavaToolInstaller": "java",
    }
    for m in re.finditer(
        r"task:\s*(\w+)(?:.*?versionSpec:\s*(.+?))?\s*$",
        text,
        re.MULTILINE | re.DOTALL,
    ):
        task = m.group(1)
        if task not in task_map:
            continue
        ver = _unquote(m.group(2) or "*") or "*"
        out.append(CiToolchain(task_map[task], ver, rel, platform))
    return out


def collect_ci_toolchains(root: Path | str) -> tuple[CiToolchain, ...]:
    """Collect every toolchain version declared by CI config in a repo."""
    root = Path(root)
    found: list[CiToolchain] = []
    for wf in _gha_workflows(root):
        found.extend(_parse_github_actions(wf, root))
    gl = root / ".gitlab-ci.yml"
    if gl.exists():
        found.extend(_parse_gitlab_ci(gl, root))
    az = root / "azure-pipelines.yml"
    if az.exists():
        found.extend(_parse_azure_pipelines(az, root))
    seen: set[tuple[str, str, str]] = set()
    unique: list[CiToolchain] = []
    for t in found:
        key = (t.tool, t.spec, t.source_file)
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return tuple(unique)


def local_vs_ci_diff(
    ci_toolchains: tuple[CiToolchain, ...],
    local_versions: dict[str, str],
) -> list[dict[str, str]]:
    """Compare CI-declared toolchains with locally active versions.

    Returns rows: {tool, ci_spec, source_file, local_version, status, detail}.
    Status: match | mismatch | unknown-local | wildcard | ci-absent.
    """
    from devrepro.core.versioning import parse_spec, parse_version

    rows: list[dict[str, str]] = []
    by_tool: dict[str, list[CiToolchain]] = {}
    for t in ci_toolchains:
        by_tool.setdefault(t.tool, []).append(t)
    tools = sorted(set(by_tool) | set(local_versions))
    for tool in tools:
        decls = by_tool.get(tool, [])
        specs = "; ".join(d.spec for d in decls) or "-"
        source = decls[0].source_file if decls else "-"
        local = local_versions.get(tool)
        if not decls:
            status, detail = "ci-absent", "declared locally but not pinned in CI"
        elif any(d.spec in ("*", "") for d in decls):
            status, detail = "wildcard", "CI does not pin an exact/range version"
        elif local is None:
            status, detail = "unknown-local", f"CI requires {specs}; no local {tool} detected"
        else:
            ok = False
            try:
                lv = parse_version(local)
                pinned = [d for d in decls if d.spec not in ("*", "")]
                ok = all(parse_spec(d.spec).satisfied_by(lv) for d in pinned)
            except Exception:
                ok = local in {d.spec for d in decls}
            if ok:
                status, detail = "match", f"local {tool} {local} satisfies CI ({specs})"
            else:
                status, detail = (
                    "mismatch",
                    (
                        f"CI pins {specs} but local {tool} is {local}; "
                        "this explains CI-vs-machine behavior differences"
                    ),
                )
        rows.append(
            {
                "tool": tool,
                "ci_spec": specs,
                "source_file": source,
                "local_version": local or "-",
                "status": status,
                "detail": detail,
            }
        )
    return rows
