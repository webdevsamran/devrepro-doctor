"""What a framework requires of the *machine*, which its manifest does not say.

Generic manifest parsing already reads the versions a project declares. What it
cannot read is the requirement one layer down: `next@15` in `package.json` says
nothing about Node 18.18, and a project that declares `>=18` and installs Next
15 has a manifest that is internally consistent and a build that fails on Node
18.0 with an error about syntax.

Three frameworks, deeply, rather than ten shallowly. Each of the three earns its
place by having a *machine* requirement that is not in any manifest:

**Next.js** pins a Node floor per major that its own `engines` field usually
does not state, and its image pipeline depends on a prebuilt native binary with
a glibc floor of its own.

**Django** pins a Python floor per major, and its database drivers split into
"needs a C compiler and a client library" and "does not" in a way that is
invisible from `requirements.txt` — `psycopg2` and `psycopg2-binary` are one
character apart and land on opposite sides of it.

**Spring Boot** pins a JDK floor per major, and the Gradle wrapper the project
ships has a *maximum* JDK it understands. A machine with a newer JDK than the
wrapper supports fails with a stack trace from Gradle's own internals, which
names neither version.

Everything here reads files already on disk. No framework is invoked: `next
info`, `manage.py check` and `gradlew --version` all start a runtime, and two of
them execute the project's own configuration.

Every floor below is a published requirement with a source comment. Where a
version is not recognised, no floor is claimed -- a guessed requirement produces
a confident wrong finding, which is worse than silence.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DJANGO_PYTHON_FLOOR",
    "NATIVE_BUILD_DEPENDENCIES",
    "NEXT_NODE_FLOOR",
    "SPRING_BOOT_JDK_FLOOR",
    "FrameworkRequirement",
    "detect_frameworks",
]

#: Next.js major -> the Node floor that major requires.
#: https://nextjs.org/docs/getting-started/installation -- each major's release
#: notes state it, and `engines` in a generated project usually does not.
NEXT_NODE_FLOOR: dict[int, str] = {
    13: "16.14.0",
    14: "18.17.0",
    15: "18.18.0",
}

#: Django major.minor -> the Python floor.
#: https://docs.djangoproject.com/en/stable/faq/install/
DJANGO_PYTHON_FLOOR: dict[str, str] = {
    "4.2": "3.8",
    "5.0": "3.10",
    "5.1": "3.10",
    "5.2": "3.10",
}

#: Spring Boot major -> the JDK floor.
#: https://docs.spring.io/spring-boot/system-requirements.html
SPRING_BOOT_JDK_FLOOR: dict[int, str] = {
    2: "8",
    3: "17",
}

#: Dependencies whose *installation* needs something on the machine that no
#: manifest mentions. The pairs that differ by one character are the point:
#: `psycopg2` compiles and `psycopg2-binary` does not, and a requirements file
#: gives no hint which one the reader is looking at.
NATIVE_BUILD_DEPENDENCIES: dict[str, tuple[str, str]] = {
    # package: (what the machine needs, why it is not obvious)
    "psycopg2": (
        "a C compiler and libpq (pg_config on PATH)",
        "`psycopg2-binary` is one character away and needs neither. A "
        "requirements file gives no hint which one you are looking at.",
    ),
    "mysqlclient": (
        "a C compiler and the MySQL/MariaDB client library",
        "The pure-Python alternatives are named nothing like it, so nobody "
        "notices this is the compiling one.",
    ),
    "sharp": (
        "prebuilt binaries for this platform, or libvips and a compiler",
        "Its prebuilt binaries carry a glibc floor, so an older distribution "
        "falls back to compiling libvips -- which is where a five-second "
        "install becomes a ten-minute one, or fails.",
    ),
    "node-gyp": (
        "a C++ toolchain and a Python interpreter",
        "It is almost never a direct dependency: it arrives underneath "
        "something else, and the failure names node-gyp rather than whatever "
        "pulled it in.",
    ),
    "canvas": (
        "Cairo, Pango and a C++ toolchain",
        "Prebuilt binaries cover common platforms only; anything else compiles.",
    ),
    "better-sqlite3": (
        "a C++ toolchain when no prebuilt binary matches",
        "Prebuilds are per Node ABI, so a Node upgrade can turn a working "
        "install into a compiling one.",
    ),
}


@dataclass(frozen=True)
class FrameworkRequirement:
    """A machine requirement a framework imposes but does not declare."""

    framework: str
    version: str
    #: The tool the requirement is about: `node`, `python`, `java`.
    tool: str
    #: The floor, as a version spec.
    required: str
    source: str
    detail: str


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _major(version: str) -> int | None:
    match = re.search(r"(\d+)", version or "")
    return int(match.group(1)) if match else None


def _major_minor(version: str) -> str | None:
    match = re.search(r"(\d+)\.(\d+)", version or "")
    return f"{match.group(1)}.{match.group(2)}" if match else None


def detect_next(root: Path) -> list[FrameworkRequirement]:
    """Next.js: the Node floor its major requires.

    Read from the *declared dependency range*, not from `node_modules`. A
    lockfile resolves the exact version, and a scan that walks `node_modules` is
    a scan that takes minutes -- but the range's lower bound is what the project
    committed to, which is the right thing to hold a machine against.
    """
    package = _read_json(root / "package.json")
    if not package:
        return []
    dependencies = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    declared = dependencies.get("next")
    if not isinstance(declared, str):
        return []

    major = _major(declared)
    floor = NEXT_NODE_FLOOR.get(major) if major is not None else None
    if floor is None:
        # An unrecognised major claims nothing. A guessed floor produces a
        # confident wrong finding, which is worse than saying nothing.
        return []

    return [
        FrameworkRequirement(
            framework="next",
            version=declared,
            tool="node",
            required=f">={floor}",
            source="package.json",
            detail=(
                f"Next.js {major} requires Node {floor} or newer. The `engines` field "
                "in a generated Next project usually does not say so, so a project "
                "declaring `>=18` and installing Next 15 is internally consistent and "
                "fails on Node 18.0 with a syntax error."
            ),
        )
    ]


#: `Django>=5.0` at the start of a line. Anchored deliberately: unanchored, it
#: matches the word in a comment, a URL or a description. That anchor is also
#: why `pyproject.toml` is parsed rather than searched -- there the name sits
#: mid-line inside an array, and loosening the regex to reach it would break the
#: file it was written for.
_DJANGO_SPEC = re.compile(r"^\s*[Dd]jango\s*(?:[<>=~!]+\s*)?([\d.]+)", re.MULTILINE)

#: `Django==4.2.11`, anywhere in a dependency *string* -- which is safe, because
#: by then the string came out of a parsed dependency list rather than out of
#: arbitrary file text.
_DJANGO_IN_SPEC = re.compile(r"^[Dd]jango\s*(?:[<>=~!^]+\s*)?([\d.]+)")


def _django_from_pyproject(path: Path) -> str | None:
    """A Django version from a parsed `pyproject.toml`, or `None`.

    Reads PEP 621 `[project.dependencies]` and Poetry's
    `[tool.poetry.dependencies]`. A Django project is about as likely to use one
    as the other, and reading only the first would miss half of them silently.
    """
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = payload.get("project")
    if isinstance(project, dict):
        for entry in project.get("dependencies") or []:
            if isinstance(entry, str):
                match = _DJANGO_IN_SPEC.match(entry.strip())
                if match:
                    return match.group(1)

    tool = payload.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    dependencies = poetry.get("dependencies") if isinstance(poetry, dict) else None
    if isinstance(dependencies, dict):
        for name, spec in dependencies.items():
            if name.lower() != "django":
                continue
            # Poetry allows `django = "^5.0"` and `django = {version = "^5.0"}`.
            raw = spec if isinstance(spec, str) else (spec or {}).get("version")
            if isinstance(raw, str):
                match = re.search(r"([\d.]+)", raw)
                if match:
                    return match.group(1)
    return None


def detect_django(root: Path) -> list[FrameworkRequirement]:
    """Django: the Python floor its release requires.

    `manage.py` alone is not enough -- it says a Django project is here and not
    which Django. The version comes from whichever dependency declaration the
    project actually uses.
    """
    if not (root / "manage.py").is_file():
        return []

    declared: str | None = None
    source = ""
    for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found = (
            _django_from_pyproject(path)
            if name == "pyproject.toml"
            else (m.group(1) if (m := _DJANGO_SPEC.search(text)) else None)
        )
        if found:
            declared, source = found, name
            break

    if declared is None:
        return []

    key = _major_minor(declared)
    floor = DJANGO_PYTHON_FLOOR.get(key) if key else None
    if floor is None:
        return []

    return [
        FrameworkRequirement(
            framework="django",
            version=declared,
            tool="python",
            required=f">={floor}",
            source=source,
            detail=(
                f"Django {key} requires Python {floor} or newer. Installing it on an "
                "older interpreter succeeds -- pip resolves an older Django instead -- "
                "so the project silently runs a different version from the one it "
                "declared."
            ),
        )
    ]


_SPRING_PLUGIN = re.compile(
    r"""id\s*\(?['"]org\.springframework\.boot['"]\)?\s*version\s*['"]([\d.]+)""",
)
_SPRING_PARENT = re.compile(
    r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>([\d.]+)",
    re.DOTALL,
)


def detect_spring_boot(root: Path) -> list[FrameworkRequirement]:
    """Spring Boot: the JDK floor its major requires.

    Gradle and Maven declare it in completely different places, and a project
    with both -- which happens during a migration -- gets read from whichever is
    found first rather than merged, because two answers here would be two
    findings about the same thing.
    """
    declared: str | None = None
    source = ""

    for name in ("build.gradle.kts", "build.gradle"):
        path = root / name
        if not path.is_file():
            continue
        try:
            match = _SPRING_PLUGIN.search(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if match:
            declared, source = match.group(1), name
            break

    if declared is None and (root / "pom.xml").is_file():
        try:
            match = _SPRING_PARENT.search((root / "pom.xml").read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match:
            declared, source = match.group(1), "pom.xml"

    if declared is None:
        return []

    major = _major(declared)
    floor = SPRING_BOOT_JDK_FLOOR.get(major) if major is not None else None
    if floor is None:
        return []

    return [
        FrameworkRequirement(
            framework="spring-boot",
            version=declared,
            tool="java",
            required=f">={floor}",
            source=source,
            detail=(
                f"Spring Boot {major}.x requires JDK {floor} or newer. On an older JDK "
                "the build fails inside the plugin with a class-version error that "
                "names a bytecode number rather than a Java version."
            ),
        )
    ]


def native_dependencies(root: Path) -> list[tuple[str, str, str, str]]:
    """Declared dependencies whose installation needs a toolchain.

    Returns `(package, source file, what is needed, why it is not obvious)`.
    Read from declarations rather than from an installed tree: `node_modules`
    is expensive to walk, and the question is what a *fresh* install on this
    machine would need.
    """
    found: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    package = _read_json(root / "package.json")
    declared_js = {
        **(package.get("dependencies") or {}),
        **(package.get("devDependencies") or {}),
    }
    for name in sorted(declared_js):
        if name in NATIVE_BUILD_DEPENDENCIES and name not in seen:
            seen.add(name)
            needs, why = NATIVE_BUILD_DEPENDENCIES[name]
            found.append((name, "package.json", needs, why))

    for filename in ("requirements.txt", "pyproject.toml"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for name, (needs, why) in NATIVE_BUILD_DEPENDENCIES.items():
            if name in seen:
                continue
            # Word-boundary matched: `psycopg2-binary` must not match
            # `psycopg2`, and that pair is the whole reason this check exists.
            if re.search(rf"^\s*{re.escape(name)}\s*(?:[<>=~!\[;]|$)", text, re.MULTILINE):
                seen.add(name)
                found.append((name, filename, needs, why))

    return found


def detect_frameworks(root: Path) -> list[FrameworkRequirement]:
    """Every framework-imposed machine requirement this repository implies."""
    requirements: list[FrameworkRequirement] = []
    requirements.extend(detect_next(root))
    requirements.extend(detect_django(root))
    requirements.extend(detect_spring_boot(root))
    return requirements
