"""Reproducibility completeness score.

A transparent heuristic: every point is explained. The score measures how
completely a project *declares* its environment — it NEVER guarantees that
a build will reproduce.
"""

from __future__ import annotations

from pathlib import Path

from devrepro.core.models import (
    ProjectRequirement,
    ReproducibilityPoint,
    ReproducibilityScore,
)

__all__ = ["compute_score"]

_LOCKFILES = {
    "python": ("poetry.lock", "uv.lock", "Pipfile.lock", "requirements.txt.lock"),
    "node": ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"),
    "go": ("go.sum",),
    "rust": ("Cargo.lock",),
    "php": ("composer.lock",),
    "ruby": ("Gemfile.lock",),
}

_TOOL_MANAGER_FILES = (
    ".nvmrc",
    ".node-version",
    ".python-version",
    ".ruby-version",
    ".java-version",
    ".tool-versions",
    "mise.toml",
    "rust-toolchain",
    "rust-toolchain.toml",
    "global.json",
)


def compute_score(
    root: Path | None, requirements: list[ProjectRequirement]
) -> ReproducibilityScore:
    points: list[ReproducibilityPoint] = []

    def add(criterion: str, earned: int, possible: int, explanation: str) -> None:
        points.append(
            ReproducibilityPoint(
                criterion=criterion,
                earned=earned,
                possible=possible,
                explanation=explanation,
            )
        )

    # 1. Declared runtime versions -------------------------------------------
    runtime_reqs = [
        r for r in requirements if r.kind.value == "runtime" and r.ecosystem != "generic"
    ]
    has_runtime_decl = bool(runtime_reqs)
    add(
        "declared-runtime-versions",
        2 if has_runtime_decl else 0,
        2,
        f"{len(runtime_reqs)} runtime version requirement(s) declared in manifests"
        if has_runtime_decl
        else "No runtime versions declared (e.g. requires-python, engines.node). "
        "Add them so machines converge on the same runtimes.",
    )

    # 2. Lockfiles --------------------------------------------------------------
    lock_reqs = [r for r in requirements if r.note == "lockfile present"]
    add(
        "dependency-lock-coverage",
        min(2, len(lock_reqs)),
        2,
        f"Lockfiles found: {', '.join(r.name for r in lock_reqs) or 'none'}. "
        "Lockfiles pin exact dependency trees.",
    )

    # 3. Compiler/runtime determinism ------------------------------------------
    pinned_tool_files = [r for r in requirements if r.source_file.endswith(_TOOL_MANAGER_FILES)]
    add(
        "compiler-runtime-determinism",
        1 if pinned_tool_files else 0,
        1,
        f"Tool-manager pin files found: {len(pinned_tool_files)}"
        if pinned_tool_files
        else "No .nvmrc/.tool-versions/rust-toolchain/global.json style pins; "
        "contributors may get different compiler/runtime versions.",
    )

    # 4. Container/devcontainer definitions --------------------------------------
    container_reqs = [r for r in requirements if r.ecosystem == "container"]
    devc = any(r.name == "devcontainer" for r in container_reqs)
    docker = any(r.name in ("docker-build", "docker-compose") for r in container_reqs)
    earned = 1 if devc else 0
    explanation = (
        "Devcontainer definition present — one-command reproducible editor environment."
        if devc
        else "No devcontainer definition; consider adding .devcontainer/devcontainer.json."
    )
    if docker:
        earned += 1
        explanation += " Container build/compose files present."
    add("container-devcontainer-definitions", earned, 2, explanation)

    # 5. Tool-manager files ---------------------------------------------------------
    root = root or Path.cwd()
    tm_present = [f for f in _TOOL_MANAGER_FILES if (root / f).is_file()]
    add(
        "tool-manager-files",
        1 if tm_present else 0,
        1,
        f"Tool-manager files committed: {', '.join(tm_present)}"
        if tm_present
        else "No tool-manager files committed (.tool-versions, mise.toml, ...).",
    )

    # 6. CI parity ---------------------------------------------------------------------
    ci_reqs = [r for r in requirements if r.name.startswith("ci:")]
    add(
        "ci-parity",
        1 if ci_reqs else 0,
        1,
        f"CI workflows declare runtimes ({', '.join(r.name for r in ci_reqs)})"
        if ci_reqs
        else "CI does not declare explicit runtime versions; local/CI drift is likely.",
    )

    total = sum(p.earned for p in points)
    possible = sum(p.possible for p in points)
    return ReproducibilityScore(total=total, possible=possible, points=tuple(points))
