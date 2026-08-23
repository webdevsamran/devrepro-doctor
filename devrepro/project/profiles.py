"""Project readiness profiles and explainable reproducibility maturity scoring.

Profiles classify a repository into a workload family (frontend, backend,
data/ml, mobile, embedded, infrastructure) from manifest evidence, then
weight requirements by what actually matters for that workload.

Scoring is deliberately honest: it measures DECLARATION COMPLETENESS
(are versions pinned? are lockfiles present? is CI declared?) — it never
claims to guarantee identical builds.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "MaturityFactor",
    "MaturityScore",
    "ProfileReport",
    "detect_profile",
    "score_maturity",
]

PROFILES = ("frontend", "backend", "data-ml", "mobile", "embedded", "infrastructure")


@dataclass(frozen=True)
class ProfileReport:
    profile: str  # primary profile or "unknown"
    confidence: float  # 0..1
    signals: tuple[str, ...]  # human-readable evidence


@dataclass(frozen=True)
class MaturityFactor:
    name: str
    weight: int
    earned: int
    detail: str

    @property
    def satisfied(self) -> bool:
        return self.earned >= self.weight


@dataclass(frozen=True)
class MaturityScore:
    total: int
    possible: int
    factors: tuple[MaturityFactor, ...] = field(default_factory=tuple)

    @property
    def percent(self) -> int:
        return round(100 * self.total / self.possible) if self.possible else 0

    def explanation(self) -> str:
        lines = [f"Declaration completeness: {self.total}/{self.possible} ({self.percent}%)."]
        lines.append(
            "This measures how completely the environment is DECLARED; "
            "it does not guarantee bit-for-bit identical builds."
        )
        for f in self.factors:
            mark = "PASS" if f.satisfied else "MISS"
            lines.append(f"  [{mark}] {f.name} (+{f.earned}/{f.weight}): {f.detail}")
        return chr(10).join(lines)


# ---- profile detection -------------------------------------------------

_PROFILE_SIGNALS: dict[str, tuple[str, ...]] = {
    "frontend": (
        "package.json",
        "vite.config.ts",
        "next.config.js",
        "next.config.mjs",
        "svelte.config.js",
        "angular.json",
        "vue.config.js",
        "tailwind.config.js",
        "index.html",
    ),
    "backend": (
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "Gemfile",
        "composer.json",
        "*.csproj",
    ),
    "data-ml": (
        "environment.yml",
        "environment.yaml",
        "Dockerfile.ml",
        "notebooks",
        "mlflow.yaml",
        "dvc.yaml",
        "params.yaml",
    ),
    "mobile": (
        "pubspec.yaml",
        "android/app/build.gradle",
        "ios/Podfile",
        "app.json",
        "react-native.config.js",
        "Info.plist",
    ),
    "embedded": (
        "platformio.ini",
        "CMakeLists.txt",
        "Makefile",
        "*.ioc",
        "sdkconfig",
    ),
    "infrastructure": (
        ".github/workflows",
        "terraform/main.tf",
        "main.tf",
        "k8s",
        "kubernetes",
        "helm",
        "Chart.yaml",
        "docker-compose.yml",
        "Vagrantfile",
    ),
}

# weights per factor per profile (0 = not applicable)
_BASE_FACTORS: dict[str, int] = {
    "runtime-pinned": 3,
    "lockfile": 3,
    "ci-declared": 2,
    "container-or-nix": 2,
    "env-doc": 1,
}


def _exists_any(root: Path, names: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for n in names:
        if n.endswith("/"):
            if (root / n.rstrip("/")).is_dir():
                hits.append(n)
        elif "*" in n:
            if any(root.glob(n)):
                hits.append(n)
        elif (root / n).exists():
            hits.append(n)
    return hits


def detect_profile(root: Path | str) -> ProfileReport:
    """Classify the repository into a workload profile from file evidence."""
    root = Path(root)
    scores: dict[str, list[str]] = {}
    for profile, markers in _PROFILE_SIGNALS.items():
        hits = _exists_any(root, markers)
        if hits:
            scores[profile] = hits
    if not scores:
        return ProfileReport("unknown", 0.0, ())
    # weight: more specific marker files win; ties broken by hit count
    best = max(scores.items(), key=lambda kv: len(kv[1]))
    total_hits = sum(len(v) for v in scores.values())
    confidence = min(1.0, len(best[1]) / max(1, total_hits))
    signals = tuple(f"{p}: {', '.join(h[:4])}" for p, h in sorted(scores.items()))
    return ProfileReport(best[0], confidence, signals)


# ---- maturity scoring --------------------------------------------------


def _read_json(path: Path) -> dict[str, object]:
    try:
        data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def score_maturity(root: Path | str) -> MaturityScore:
    """Explainable declaration-completeness score for the repository."""
    root = Path(root)
    factors: list[MaturityFactor] = []

    # runtime-pinned: engines/requires-python/toolchain directives present
    pinned_evidence: list[str] = []
    pkg = _read_json(root / "package.json")
    engines = pkg.get("engines")
    if isinstance(engines, dict) and engines.get("node"):
        pinned_evidence.append("package.json#engines.node")
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            proj = data.get("project")
            if isinstance(proj, dict) and isinstance(proj.get("requires-python"), str):
                pinned_evidence.append("pyproject.toml#requires-python")
        except (OSError, tomllib.TOMLDecodeError):
            pass
    gomod = root / "go.mod"
    if gomod.is_file():
        try:
            text = gomod.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.lstrip().startswith(("go ", "module ")) and ("go 1." in text):
            pinned_evidence.append("go.mod#go")
    rust_toolchain = (root / "rust-toolchain.toml").exists() or (root / "rust-toolchain").exists()
    if rust_toolchain:
        pinned_evidence.append("rust-toolchain")
    # a single authoritative pin (engines/requires-python/toolchain) satisfies it
    earned = _BASE_FACTORS["runtime-pinned"] if pinned_evidence else 0
    factors.append(
        MaturityFactor(
            "runtime-pinned",
            _BASE_FACTORS["runtime-pinned"],
            earned,
            "; ".join(pinned_evidence) or "no runtime version pins found",
        )
    )

    # lockfile
    locks = [
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "go.sum",
        "composer.lock",
        "Gemfile.lock",
        "packages.lock.json",
    ]
    found_locks = [lk for lk in locks if (root / lk).is_file()]
    lock_earned = _BASE_FACTORS["lockfile"] if found_locks else 0
    factors.append(
        MaturityFactor(
            "lockfile",
            _BASE_FACTORS["lockfile"],
            lock_earned,
            ", ".join(found_locks) if found_locks else "no dependency lockfile at repo root",
        )
    )

    # ci-declared
    ci_files = [
        ".github/workflows",
        ".gitlab-ci.yml",
        "azure-pipelines.yml",
        ".circleci/config.yml",
        "Jenkinsfile",
    ]
    ci_found = [c for c in ci_files if (root / c).exists()]
    ci_earned = _BASE_FACTORS["ci-declared"] if ci_found else 0
    factors.append(
        MaturityFactor(
            "ci-declared",
            _BASE_FACTORS["ci-declared"],
            ci_earned,
            ", ".join(ci_found) if ci_found else "no CI pipeline configuration found",
        )
    )

    # container-or-nix
    repro_files = [
        "Dockerfile",
        "docker-compose.yml",
        "compose.yaml",
        "flake.nix",
        "devenv.nix",
        "devbox.json",
        ".devcontainer/devcontainer.json",
    ]
    repro_found = [r for r in repro_files if (root / r).exists()]
    repro_earned = _BASE_FACTORS["container-or-nix"] if repro_found else 0
    factors.append(
        MaturityFactor(
            "container-or-nix",
            _BASE_FACTORS["container-or-nix"],
            repro_earned,
            ", ".join(repro_found) if repro_found else "no container/Nix/devbox definition",
        )
    )

    # env-doc
    env_docs = [".env.example", "ENVIRONMENT.md", "docs/environment.md", "SETUP.md"]
    env_found = [e for e in env_docs if (root / e).exists()]
    env_earned = _BASE_FACTORS["env-doc"] if env_found else 0
    factors.append(
        MaturityFactor(
            "env-doc",
            _BASE_FACTORS["env-doc"],
            env_earned,
            ", ".join(env_found) if env_found else "no .env.example / environment docs",
        )
    )

    total = sum(f.earned for f in factors)
    possible = sum(f.weight for f in factors)
    return MaturityScore(total=total, possible=possible, factors=tuple(factors))
