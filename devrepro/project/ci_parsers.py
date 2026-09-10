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

__all__ = [
    "CiToolchain",
    "collect_ci_toolchains",
    "local_vs_ci_diff",
    "parse_workflow_matrices",
]


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
    """Strip surrounding whitespace, then quotes -- in that order.

    The other order is a bug that hid until a flow sequence was split on
    commas: `["3.11", "3.12"]` yields ` "3.12"`, whose first character is a
    space, so stripping quotes removes only the trailing one and leaves
    `"3.12`. Every caller that passes the right-hand side of a `split(":", 1)`
    has the same leading space.
    """
    return v.strip().strip("".join(_QUOTE)).strip()


def _parse_github_actions(path: Path, root: Path) -> list[CiToolchain]:
    out: list[CiToolchain] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rel = path.relative_to(root).as_posix()

    # Read every job's matrix up front. Which job a step belongs to is not
    # tracked by this line scanner, so a reference resolves against the union
    # of the file's axes. That over-resolves in a workflow whose jobs declare
    # the same axis name with different values -- rare, and the failure mode is
    # reporting a version CI does test somewhere, which beats reporting "any".
    matrices = parse_workflow_matrices(lines)
    axes: dict[str, tuple[str, ...]] = {}
    for job_axes in matrices.values():
        for key, values in job_axes.items():
            merged = list(axes.get(key, ()))
            merged.extend(v for v in values if v not in merged)
            axes[key] = tuple(merged)

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
                if "${{" in spec:
                    # A matrix reference is not a wildcard. Collapsing
                    # `${{ matrix.python-version }}` to `*` threw away the four
                    # versions this repository's own CI tests, and made the
                    # local-vs-CI check say nothing on the workflows most worth
                    # checking. Resolve it where the matrix is readable, and
                    # fall back to `*` where it is not.
                    resolved = _resolve_matrix_ref(spec, axes)
                    for value in resolved or ("*",):
                        out.append(CiToolchain(m_with.group(1), value, rel, runs_on))
                else:
                    out.append(CiToolchain(m_with.group(1), spec, rel, runs_on))
            elif current_action in _SETUP_ACTIONS and stripped.startswith("version:"):
                v = _unquote(stripped.split(":", 1)[1])
                if v:
                    out.append(CiToolchain(_SETUP_ACTIONS[current_action], v, rel, runs_on))
        if indent <= current_indent:
            current_action = None
        m_run = re.match(r"runs-on:\s*(.+?)\s*$", stripped)
        if m_run:
            raw_runs_on = _unquote(m_run.group(1))
            if "${{" in raw_runs_on:
                resolved_os = _resolve_matrix_ref(raw_runs_on, axes)
                runs_on = ", ".join(resolved_os) if resolved_os else raw_runs_on
            else:
                runs_on = raw_runs_on
    return out


#: `${{ matrix.python-version }}` and friends, captured to the axis name.
_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([\w.-]+)\s*\}\}")

#: A flow sequence: `python-version: ["3.11", "3.12"]`.
_FLOW_LIST = re.compile(r"^([\w.-]+):\s*\[(.*)\]\s*(?:#.*)?$")

#: The opening of a block sequence: `python-version:` with items beneath it.
_BLOCK_KEY = re.compile(r"^([\w.-]+):\s*(?:#.*)?$")

#: One item of a block sequence: `- "3.11"`.
_BLOCK_ITEM = re.compile(r"^-\s*(.+?)\s*(?:#.*)?$")

#: Keys inside `matrix:` that are not axes.
_MATRIX_META = {"include", "exclude", "fail-fast"}


def parse_workflow_matrices(lines: list[str]) -> dict[str, dict[str, tuple[str, ...]]]:
    """Matrix axes per job, from the text of one workflow file.

    A twelve-leg matrix -- three operating systems by four Python versions --
    reached the rest of this module as the single string ``"*"``, because
    ``${{ matrix.python-version }}`` is a template rather than a version. So a
    repository that tests four Pythons and a machine running a fifth compared
    as "CI declares anything", and the check that exists to catch exactly that
    said nothing. This reads the matrix so the reference can be resolved.

    Text, not YAML, for the same reason as the rest of the file: a diagnostic
    tool that cannot read a workflow without a parsing dependency is one more
    thing to install before you can find out why nothing installs. Both
    sequence styles are handled, plus the ``include:`` entries that add legs
    outside the cross-product.

    Returns ``{job_name: {axis: (value, ...)}}``. Jobs with no matrix are
    absent rather than empty, so a caller can tell "no matrix" from "a matrix
    whose axes were unreadable".
    """
    matrices: dict[str, dict[str, list[str]]] = {}

    jobs_indent: int | None = None
    job: str | None = None
    job_indent = 0
    matrix_indent: int | None = None
    axis: str | None = None
    axis_indent = 0
    in_include = False

    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        text = raw.strip()

        if jobs_indent is None:
            if text == "jobs:":
                jobs_indent = indent
            continue

        # Leaving the `jobs:` block entirely.
        if indent <= jobs_indent and text != "jobs:":
            jobs_indent = None
            job = None
            matrix_indent = None
            continue

        # A job header: the only mapping key directly under `jobs:`.
        if job is None or indent <= job_indent:
            header = re.match(r"^([\w.-]+):\s*(?:#.*)?$", text)
            if header and indent > jobs_indent:
                job = header.group(1)
                job_indent = indent
                matrix_indent = None
                axis = None
                in_include = False
                continue

        if job is None:
            continue

        if matrix_indent is None:
            if text == "matrix:":
                matrix_indent = indent
                matrices.setdefault(job, {})
            continue

        # Left the matrix block.
        if indent <= matrix_indent:
            matrix_indent = None
            axis = None
            in_include = False
            continue

        axes = matrices.setdefault(job, {})

        # `include:` adds legs that are not in the cross-product. Its nested
        # `key: value` pairs are values for those keys just the same, so they
        # are folded in rather than skipped -- a workflow that adds one
        # experimental Python only in `include` really does test it.
        if text in {"include:", "exclude:"}:
            in_include = text == "include:"
            axis = None
            axis_indent = indent
            continue

        if in_include and indent > axis_indent:
            pair = re.match(r"^-?\s*([\w.-]+):\s*(.+?)\s*(?:#.*)?$", text)
            if pair and pair.group(1) not in _MATRIX_META:
                value = _unquote(pair.group(2))
                if value and "${{" not in value:
                    axes.setdefault(pair.group(1), [])
                    if value not in axes[pair.group(1)]:
                        axes[pair.group(1)].append(value)
            continue

        flow = _FLOW_LIST.match(text)
        if flow and flow.group(1) not in _MATRIX_META:
            values = [_unquote(v) for v in flow.group(2).split(",")]
            axes[flow.group(1)] = [v for v in values if v and "${{" not in v]
            axis = None
            continue

        block = _BLOCK_KEY.match(text)
        if block and block.group(1) not in _MATRIX_META:
            axis = block.group(1)
            axis_indent = indent
            axes.setdefault(axis, [])
            continue

        if axis is not None and indent > axis_indent:
            item = _BLOCK_ITEM.match(text)
            if item:
                value = _unquote(item.group(1))
                if value and "${{" not in value and value not in axes[axis]:
                    axes[axis].append(value)
            continue

    return {job: {k: tuple(v) for k, v in axes.items() if v} for job, axes in matrices.items()}


def _resolve_matrix_ref(spec: str, axes: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Every concrete value a `${{ matrix.x }}` reference stands for.

    Returns an empty tuple when the reference cannot be resolved -- an axis
    defined in a reusable workflow, or one built from a `fromJSON` expression.
    The caller keeps the wildcard in that case, which is the honest answer:
    "this is templated and we could not read it" is not the same claim as
    "this accepts any version".
    """
    ref = _MATRIX_REF.search(spec)
    if not ref:
        return ()
    return axes.get(ref.group(1), ())


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
