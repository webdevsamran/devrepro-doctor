"""What a lockfile says the machine must be able to run.

Lockfiles were presence-only here: ``_lockfiles`` in ``detectors.py`` records
that one exists, which is a reproducibility signal and nothing more. But a
lockfile also carries a *format version*, and a format version is a requirement
on the machine -- npm 6 handed a ``lockfileVersion: 3`` file does not read it,
it silently rewrites the entire tree; cargo 1.52 cannot open a ``version = 4``
``Cargo.lock`` at all; yarn 1 cannot install from a Berry lock.

That is this project's thesis in one file: the repository declares something,
the machine provides something else, and the failure surfaces far from the
cause. So this module parses exactly two things out of each lockfile --

* the format version, and the tool range that format implies, and
* any runtime pin the file records (``requires-python``, ``engines``,
  ``RUBY VERSION``)

-- and nothing about the dependency graph. Package *contents* are the project's
business; package *format* is the machine's.

Every parser is tolerant: a lockfile it cannot read produces a fact carrying the
reason, never an exception. A diagnostic tool that crashes on a malformed input
is worse than one that says it could not tell.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "LOCKFILE_PARSERS",
    "LockfileFacts",
    "collect_lockfile_facts",
    "parse_lockfile",
]

#: How far below the root to look. Matches ``_MAX_LOCKFILE_DEPTH`` in
#: ``detectors.py`` so the two never disagree about which files exist.
MAX_DEPTH = 3

_SKIP_DIRS = frozenset(
    {
        "node_modules",
        "vendor",
        "target",
        "dist",
        "build",
        "site",
        "venv",
        "__pycache__",
    }
)


@dataclass(frozen=True)
class LockfileFacts:
    """What one lockfile requires of the machine.

    ``minimum_tool`` is deliberately optional. Some formats map to a published,
    stable floor (a ``Cargo.lock`` ``version = 4`` needs cargo 1.78); others do
    not, and inventing one would make the tool confidently wrong. When the floor
    is unknown the format version is still reported, because "this is a v2
    uv.lock" is useful even when "and therefore you need uv X" is not knowable.
    """

    path: str
    ecosystem: str
    tool: str
    format_version: str | None = None
    minimum_tool: str | None = None
    #: A tool version the file records as having produced it, e.g. the
    #: ``BUNDLED WITH`` section of a ``Gemfile.lock``. Informational only.
    produced_by: str | None = None
    #: ``(runtime name, version spec)`` the lockfile pins, e.g.
    #: ``("python", ">=3.11")``.
    requires_runtime: tuple[str, str] | None = None
    entries: int | None = None
    note: str = ""
    unreadable: bool = False


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _json(path: Path) -> tuple[dict[str, Any] | None, str]:
    text = _text(path)
    if text is None:
        return None, "could not be read"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"is not valid JSON: {exc.msg} (line {exc.lineno})"
    if not isinstance(data, dict):
        return None, "is valid JSON but not an object"
    return data, ""


def _toml(path: Path) -> tuple[dict[str, Any] | None, str]:
    text = _text(path)
    if text is None:
        return None, "could not be read"
    try:
        return tomllib.loads(text), ""
    except tomllib.TOMLDecodeError as exc:
        return None, f"is not valid TOML: {exc}"


def _unreadable(rel: str, ecosystem: str, tool: str, why: str) -> LockfileFacts:
    return LockfileFacts(path=rel, ecosystem=ecosystem, tool=tool, note=why, unreadable=True)


# ------------------------------------------------------------------- node


#: ``lockfileVersion`` -> the npm range that can use the file as written.
#:
#: v1 is npm 5/6's format and every later npm reads it. v2 is a hybrid: it
#: carries both the new ``packages`` map and the legacy ``dependencies`` tree, so
#: npm 6 can still install from it, degraded. v3 drops the legacy tree, and that
#: is where npm 6 stops working -- it rewrites the file rather than failing,
#: which is precisely the class of failure this tool exists to catch.
_NPM_LOCK_VERSIONS: dict[int, tuple[str, str]] = {
    1: (">=5", "npm 5 or newer reads this format"),
    2: (
        ">=7",
        "npm 7 or newer; npm 6 can still install from the legacy tree this format retains",
    ),
    3: (
        ">=7",
        "npm 7 or newer -- the legacy dependency tree is absent, so npm 6 rewrites the file",
    ),
}


def _npm(path: Path, rel: str) -> LockfileFacts:
    data, why = _json(path)
    if data is None:
        return _unreadable(rel, "node", "npm", why)

    raw = data.get("lockfileVersion")
    version = raw if isinstance(raw, int) else None
    minimum, note = _NPM_LOCK_VERSIONS.get(version or -1, (None, ""))

    requires: tuple[str, str] | None = None
    entries: int | None = None
    packages = data.get("packages")
    if isinstance(packages, dict):
        # The empty key is the root project's own entry.
        entries = max(len(packages) - 1, 0)
        root = packages.get("")
        if isinstance(root, dict):
            engines = root.get("engines")
            if isinstance(engines, dict):
                node_spec = engines.get("node")
                if isinstance(node_spec, str) and node_spec.strip():
                    requires = ("node", node_spec.strip())

    return LockfileFacts(
        path=rel,
        ecosystem="node",
        tool="npm",
        format_version=str(version) if version is not None else None,
        minimum_tool=minimum,
        requires_runtime=requires,
        entries=entries,
        note=note,
    )


#: pnpm's own lockfile version, quoted in the YAML. Only the transitions pnpm
#: documents as breaking are listed; an unlisted version reports no floor.
_PNPM_LOCK_VERSIONS: dict[str, str] = {
    "5.3": ">=6",
    "5.4": ">=7",
    "6.0": ">=8",
    "9.0": ">=9",
}

_PNPM_VERSION = re.compile(r"""^lockfileVersion:\s*['"]?([0-9]+(?:\.[0-9]+)?)""", re.M)


def _pnpm(path: Path, rel: str) -> LockfileFacts:
    # Read with a regex rather than a YAML parser on purpose: this takes one
    # scalar off the top of the file, and the project has no runtime YAML
    # dependency. Adding one to learn a version number is not a good trade.
    text = _text(path)
    if text is None:
        return _unreadable(rel, "node", "pnpm", "could not be read")
    match = _PNPM_VERSION.search(text)
    version = match.group(1) if match else None
    return LockfileFacts(
        path=rel,
        ecosystem="node",
        tool="pnpm",
        format_version=version,
        minimum_tool=_PNPM_LOCK_VERSIONS.get(version or ""),
    )


_YARN_BERRY = re.compile(r"^__metadata:", re.M)
_YARN_BERRY_VERSION = re.compile(r"^\s+version:\s*([0-9]+)", re.M)


def _yarn(path: Path, rel: str) -> LockfileFacts:
    text = _text(path)
    if text is None:
        return _unreadable(rel, "node", "yarn", "could not be read")
    if _YARN_BERRY.search(text):
        version = _YARN_BERRY_VERSION.search(text)
        return LockfileFacts(
            path=rel,
            ecosystem="node",
            tool="yarn",
            format_version=f"berry/{version.group(1)}" if version else "berry",
            minimum_tool=">=2",
            note="Yarn Berry format; yarn 1.x cannot install from it",
        )
    return LockfileFacts(
        path=rel,
        ecosystem="node",
        tool="yarn",
        format_version="classic",
        minimum_tool=">=1",
        note="Yarn classic format",
    )


def _bun_text(path: Path, rel: str) -> LockfileFacts:
    return LockfileFacts(
        path=rel,
        ecosystem="node",
        tool="bun",
        format_version="text",
        minimum_tool=">=1.2",
        note="bun.lock is the text format introduced in bun 1.2",
    )


def _bun_binary(path: Path, rel: str) -> LockfileFacts:
    # Deliberately not decoded. It is a binary format with no stable published
    # layout, and guessing at offsets would produce exactly the confidently
    # wrong answer this module is built to avoid.
    return LockfileFacts(
        path=rel,
        ecosystem="node",
        tool="bun",
        format_version="binary",
        note="bun.lockb is binary; its contents are not inspected",
    )


# ----------------------------------------------------------------- python


#: poetry's ``[metadata] lock-version``.
_POETRY_LOCK_VERSIONS: dict[str, str] = {
    "1.1": ">=1.1",
    "2.0": ">=1.5",
    "2.1": ">=2.0",
}


def _poetry(path: Path, rel: str) -> LockfileFacts:
    data, why = _toml(path)
    if data is None:
        return _unreadable(rel, "python", "poetry", why)

    raw_meta = data.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    raw = meta.get("lock-version")
    version = str(raw) if isinstance(raw, (str, int, float)) else None

    requires: tuple[str, str] | None = None
    pinned = meta.get("python-versions")
    if isinstance(pinned, str) and pinned.strip():
        requires = ("python", pinned.strip())

    packages = data.get("package")
    return LockfileFacts(
        path=rel,
        ecosystem="python",
        tool="poetry",
        format_version=version,
        minimum_tool=_POETRY_LOCK_VERSIONS.get(version or ""),
        requires_runtime=requires,
        entries=len(packages) if isinstance(packages, list) else None,
    )


def _uv(path: Path, rel: str) -> LockfileFacts:
    data, why = _toml(path)
    if data is None:
        return _unreadable(rel, "python", "uv", why)
    raw = data.get("version")
    requires: tuple[str, str] | None = None
    pinned = data.get("requires-python")
    if isinstance(pinned, str) and pinned.strip():
        requires = ("python", pinned.strip())
    packages = data.get("package")
    # No ``minimum_tool``: uv's lock revisions move quickly and are not published
    # as a stable floor, so the version is reported and no requirement inferred.
    return LockfileFacts(
        path=rel,
        ecosystem="python",
        tool="uv",
        format_version=str(raw) if isinstance(raw, (str, int)) else None,
        requires_runtime=requires,
        entries=len(packages) if isinstance(packages, list) else None,
    )


def _pipenv(path: Path, rel: str) -> LockfileFacts:
    data, why = _json(path)
    if data is None:
        return _unreadable(rel, "python", "pipenv", why)

    raw_meta = data.get("_meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    requires: tuple[str, str] | None = None
    block = meta.get("requires")
    if isinstance(block, dict):
        pinned = block.get("python_full_version") or block.get("python_version")
        if isinstance(pinned, str) and pinned.strip():
            # Pipfile records an exact version, not a range.
            requires = ("python", f"=={pinned.strip()}")

    default = data.get("default")
    return LockfileFacts(
        path=rel,
        ecosystem="python",
        tool="pipenv",
        requires_runtime=requires,
        entries=len(default) if isinstance(default, dict) else None,
    )


# ------------------------------------------------------------------- rust


#: ``Cargo.lock``'s ``version``, and the cargo release that introduced support.
#: These are published, stable floors, which is why a requirement is asserted
#: here and not for formats whose history is fuzzier.
_CARGO_LOCK_VERSIONS: dict[int, str] = {3: ">=1.53", 4: ">=1.78"}


def _cargo(path: Path, rel: str) -> LockfileFacts:
    data, why = _toml(path)
    if data is None:
        return _unreadable(rel, "rust", "cargo", why)
    raw = data.get("version")
    version = raw if isinstance(raw, int) else None
    packages = data.get("package")
    return LockfileFacts(
        path=rel,
        ecosystem="rust",
        tool="cargo",
        # Absent means v1/v2, the pre-2021 formats every current cargo reads.
        format_version=str(version) if version is not None else "1 or 2 (implicit)",
        minimum_tool=_CARGO_LOCK_VERSIONS.get(version) if version is not None else None,
        entries=len(packages) if isinstance(packages, list) else None,
    )


# ------------------------------------------------------------- php, ruby, go


def _composer(path: Path, rel: str) -> LockfileFacts:
    data, why = _json(path)
    if data is None:
        return _unreadable(rel, "php", "composer", why)

    api = data.get("plugin-api-version")
    minimum: str | None = None
    if isinstance(api, str) and api.strip():
        major = api.strip().split(".")[0]
        if major.isdigit():
            minimum = f">={major}"

    requires: tuple[str, str] | None = None
    platform = data.get("platform")
    if isinstance(platform, dict):
        php = platform.get("php")
        if isinstance(php, str) and php.strip():
            requires = ("php", php.strip())

    packages = data.get("packages")
    return LockfileFacts(
        path=rel,
        ecosystem="php",
        tool="composer",
        format_version=api.strip() if isinstance(api, str) else None,
        minimum_tool=minimum,
        requires_runtime=requires,
        entries=len(packages) if isinstance(packages, list) else None,
    )


_BUNDLED_WITH = re.compile(r"^BUNDLED WITH\s*\n\s+([0-9][0-9A-Za-z.-]*)", re.M)
_RUBY_VERSION = re.compile(r"^RUBY VERSION\s*\n\s+ruby\s+([0-9][0-9A-Za-z.]*)", re.M)


def _bundler(path: Path, rel: str) -> LockfileFacts:
    text = _text(path)
    if text is None:
        return _unreadable(rel, "ruby", "bundler", "could not be read")
    bundled = _BUNDLED_WITH.search(text)
    ruby = _RUBY_VERSION.search(text)
    return LockfileFacts(
        path=rel,
        ecosystem="ruby",
        tool="bundler",
        produced_by=bundled.group(1) if bundled else None,
        requires_runtime=("ruby", f"=={ruby.group(1)}") if ruby else None,
        note="" if bundled else "no BUNDLED WITH section; bundler version unrecorded",
    )


_GO_SUM_LINE = re.compile(r"^\S+\s+\S+\s+h1:", re.M)


def _go_sum(path: Path, rel: str) -> LockfileFacts:
    text = _text(path)
    if text is None:
        return _unreadable(rel, "go", "go", "could not be read")
    # ``go.sum`` carries checksums and no version metadata at all; the toolchain
    # requirement lives in ``go.mod``, which ``detectors.py`` already reads.
    # Counting module hashes is the only fact here worth reporting.
    return LockfileFacts(
        path=rel,
        ecosystem="go",
        tool="go",
        entries=len(_GO_SUM_LINE.findall(text)),
        note="go.sum records checksums only; the toolchain floor is in go.mod",
    )


#: Filename -> parser.
LOCKFILE_PARSERS: dict[str, Callable[[Path, str], LockfileFacts]] = {
    "Cargo.lock": _cargo,
    "Gemfile.lock": _bundler,
    "Pipfile.lock": _pipenv,
    "bun.lock": _bun_text,
    "bun.lockb": _bun_binary,
    "composer.lock": _composer,
    "go.sum": _go_sum,
    "npm-shrinkwrap.json": _npm,
    "package-lock.json": _npm,
    "pnpm-lock.yaml": _pnpm,
    "poetry.lock": _poetry,
    "uv.lock": _uv,
    "yarn.lock": _yarn,
}


def parse_lockfile(path: Path, *, rel: str | None = None) -> LockfileFacts | None:
    """Facts for one lockfile, or None when the name is not a known lockfile."""
    parser = LOCKFILE_PARSERS.get(path.name)
    if parser is None:
        return None
    return parser(path, rel if rel is not None else path.name)


def _walk(root: Path, max_depth: int) -> list[Path]:
    """Directories at or below ``root``, pruned and depth-bounded."""
    found = [root]
    frontier = [(root, 0)]
    while frontier:
        directory, depth = frontier.pop()
        if depth >= max_depth:
            continue
        try:
            children = sorted(p for p in directory.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            if child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            found.append(child)
            frontier.append((child, depth + 1))
    return found


def collect_lockfile_facts(root: Path, *, max_depth: int = MAX_DEPTH) -> list[LockfileFacts]:
    """Every lockfile at or below ``root``, parsed for machine requirements.

    Read-only and offline, like everything else here: it opens files already on
    disk and never runs a package manager to ask what it thinks.
    """
    facts: list[LockfileFacts] = []
    for directory in _walk(root, max_depth):
        for name in sorted(LOCKFILE_PARSERS):
            candidate = directory / name
            if not candidate.is_file():
                continue
            try:
                rel = candidate.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - defensive
                rel = candidate.name
            parsed = parse_lockfile(candidate, rel=rel)
            if parsed is not None:
                facts.append(parsed)
    return sorted(facts, key=lambda f: f.path)
