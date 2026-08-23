"""Environment-variable tracing, policy checks and dotenv safety scanning.

Capabilities:
- trace where required env-var NAMES are declared (project files, shell
  profiles) without ever recording their VALUES;
- policy checking: required names present, forbidden names absent,
  duplicate definitions across files;
- dotenv safety: detect tracked ``.env`` files and probable credentials,
  reporting names/shapes only — never values.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DotenvFinding",
    "EnvOrigin",
    "EnvPolicyReport",
    "dotenv_safety_scan",
    "trace_env_origins",
    "verify_env_policy",
]

# files that commonly declare env vars for a project
_PROJECT_ENV_SOURCES = (
    ".env",
    ".env.local",
    ".env.example",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
    ".devcontainer/devcontainer.json",
    ".devrepro.toml",
)

_SECRET_NAME_PATTERNS = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)"
)

# value shapes that look like live credentials (used ONLY to flag, never stored)
_VALUE_SHAPES = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),  # GitHub PAT
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style key
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
)


@dataclass(frozen=True)
class EnvOrigin:
    """One declaration site for an env-var NAME."""

    name: str
    source_file: str  # repo-relative
    kind: str  # dotenv | compose | devcontainer | policy | shell-profile
    has_value_in_file: bool  # True when a concrete value sits in the file


@dataclass(frozen=True)
class DotenvFinding:
    path: str
    severity: str  # info | warn | critical
    detail: str


@dataclass(frozen=True)
class EnvPolicyReport:
    origins: tuple[EnvOrigin, ...] = ()
    missing_required: tuple[str, ...] = ()
    forbidden_present: tuple[str, ...] = ()
    duplicated: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dotenv_findings: tuple[DotenvFinding, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing_required or self.forbidden_present or self.duplicated)


def _iter_env_files(root: Path) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for rel in _PROJECT_ENV_SOURCES:
        p = root / rel
        if p.is_file():
            out.append((p, rel))
    # any additional .env* files at root
    for p in sorted(root.glob(".env*")):
        if p.name not in {rel for _, rel in out} and p.is_file():
            out.append((p, p.name))
    return out


def trace_env_origins(root: Path | str) -> tuple[EnvOrigin, ...]:
    """Find which env-var NAMES the project declares, and where."""
    root = Path(root)
    origins: list[EnvOrigin] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, src: str, kind: str, has_value: bool) -> None:
        key = (name, src)
        if name and key not in seen:
            seen.add(key)
            origins.append(
                EnvOrigin(name=name, source_file=src, kind=kind, has_value_in_file=has_value)
            )

    for path, rel in _iter_env_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix == ".json":
            for m in re.finditer(r'"([^"]+)"\s*:\s*\{[^{}]*?"value"', text):
                add(m.group(1), rel, "devcontainer", True)
            continue
        if path.suffix in {".yml", ".yaml"}:
            for m in re.finditer(r"^\s*-?\s*([A-Z_][A-Z0-9_]{1,})\s*[=:]", text, re.MULTILINE):
                add(m.group(1), rel, "compose", True)
            continue
        if path.suffix == ".toml":
            for m in re.finditer(r"names\s*=\s*\[([^\]]*)\]", text):
                for n in re.findall(r'"([^"]+)"', m.group(1)):
                    add(n, rel, "policy", False)
            continue
        # dotenv-style
        for raw_line in text.splitlines():
            stripped_line = raw_line.strip()
            if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
                continue
            name, _, value = stripped_line.partition("=")
            add(name.strip(), rel, "dotenv", bool(value.strip()))
    return tuple(origins)


def verify_env_policy(
    root: Path | str,
    required: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
) -> EnvPolicyReport:
    """Check declared env names against required/forbidden policy lists."""
    root = Path(root)
    origins = trace_env_origins(root)
    declared = {o.name for o in origins}
    by_name: dict[str, list[str]] = {}
    for o in origins:
        by_name.setdefault(o.name, []).append(o.source_file)
    duplicated = {
        n: tuple(sorted(set(files))) for n, files in by_name.items() if len(set(files)) > 1
    }
    findings = dotenv_safety_scan(root)
    return EnvPolicyReport(
        origins=origins,
        missing_required=tuple(sorted(set(required) - declared)),
        forbidden_present=tuple(sorted(set(forbidden) & declared)),
        duplicated=duplicated,
        dotenv_findings=findings,
    )


def dotenv_safety_scan(root: Path | str) -> tuple[DotenvFinding, ...]:
    """Flag tracked .env files and probable credential SHAPES (values never kept)."""
    root = Path(root)
    findings: list[DotenvFinding] = []
    gitignore = root / ".gitignore"
    ignored_patterns: list[str] = []
    if gitignore.is_file():
        with contextlib.suppress(OSError):
            ignored_patterns = [
                ln.strip()
                for ln in gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip() and not ln.startswith("#")
            ]

    def is_ignored(name: str) -> bool:
        return any(
            p.rstrip("/") == name or p == f"{name}" or p.startswith(f"{name}")
            for p in ignored_patterns
        )

    for path, rel in _iter_env_files(root):
        if not path.name.startswith(".env"):
            continue
        tracked_risk = not is_ignored(path.name)
        if tracked_risk and path.name != ".env.example":
            findings.append(
                DotenvFinding(
                    rel, "critical", f"{path.name} exists but is NOT covered by .gitignore"
                )
            )
        else:
            findings.append(
                DotenvFinding(rel, "info", f"{path.name} is gitignored (or an example template)")
            )
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        secret_names: list[str] = []
        shape_hits = 0
        for raw_line in text.splitlines():
            stripped_line = raw_line.strip()
            if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
                continue
            name, _, value = stripped_line.partition("=")
            name = name.strip()
            if _SECRET_NAME_PATTERNS.search(name):
                secret_names.append(name)
            if any(rx.search(value) for rx in _VALUE_SHAPES):
                shape_hits += 1
        if secret_names:
            sev = "critical" if tracked_risk else "warn"
            findings.append(
                DotenvFinding(
                    rel,
                    sev,
                    f"contains secret-looking variable NAMES ({len(secret_names)}); "
                    f"values were not recorded",
                )
            )
        if shape_hits:
            findings.append(
                DotenvFinding(
                    rel,
                    "critical" if tracked_risk else "warn",
                    f"{shape_hits} value(s) match known credential formats; rotate if this "
                    "file was ever committed",
                )
            )
    return tuple(findings)
