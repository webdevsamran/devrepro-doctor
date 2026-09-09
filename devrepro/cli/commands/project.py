"""Project commands: project, monorepo, ci-diff, generate, profile, baseline."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from devrepro.cli.common import (
    JsonOption,
    emit,
    local_tool_versions,
)
from devrepro.core.exit_codes import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable


def register(app: typer.Typer) -> None:
    """Attach project commands to the root app."""

    @app.command()
    def project(
        path: Path = typer.Argument(Path(), help="Project root."),
        json_out: bool = JsonOption,
    ) -> None:
        """Show what this project declares (requirements, lockfiles, CI)."""
        from devrepro.project.detectors import detect_project_kind, detect_requirements

        kinds = detect_project_kind(path)
        reqs = detect_requirements(path)
        payload = {
            "kinds": kinds,
            "requirements": [r.model_dump(mode="json") for r in reqs],
        }
        if json_out:
            emit(payload, True)
        else:
            typer.echo(f"Ecosystems: {', '.join(kinds) or 'none detected'}")
            for r in reqs:
                note = f" ({r.note})" if r.note else ""
                typer.echo(f"  [{r.ecosystem}] {r.name} {r.spec!r} <- {r.source_file}{note}")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def monorepo(
        path: Path = typer.Argument(Path(), help="Repository root."),
        json_out: bool = JsonOption,
    ) -> None:
        """Monorepo discovery, nested-project conflicts, languages, lockfiles."""
        from devrepro.project.monorepo import analyze_monorepo

        report = analyze_monorepo(path)
        payload = {
            "root": report.root,
            "is_monorepo": report.is_monorepo,
            "workspace_markers": list(report.workspace_markers),
            "projects": [
                {"path": p.path, "ecosystem": p.ecosystem, "depth": p.depth}
                for p in report.projects
            ],
            "conflicts": [
                {
                    "tool": c.tool,
                    "parent_path": c.parent_path,
                    "parent_spec": c.parent_spec,
                    "child_path": c.child_path,
                    "child_spec": c.child_spec,
                    "detail": c.detail,
                }
                for c in report.conflicts
            ],
            "inventory": {
                "languages": report.inventory.languages,
                "manifest_languages": list(report.inventory.manifest_languages),
            },
            "lockfiles": {
                "covered": list(report.lockfiles.covered),
                "uncovered": list(report.lockfiles.uncovered),
            },
        }
        if json_out:
            emit(payload, True)
        else:
            markers = ", ".join(report.workspace_markers) or "no markers"
            typer.echo(f"Monorepo: {report.is_monorepo} ({markers})")
            typer.echo(f"Projects: {len(report.projects)}")
            for c in report.conflicts:
                typer.secho(
                    f"  CONFLICT {c.tool}: {c.parent_path} wants {c.parent_spec}; "
                    f"{c.child_path} wants {c.child_spec}",
                    fg=typer.colors.RED,
                )
            if report.lockfiles.uncovered:
                typer.secho(
                    f"No lockfile for: {', '.join(report.lockfiles.uncovered)}",
                    fg=typer.colors.YELLOW,
                )
        raise typer.Exit(ExitCode.BLOCKED if report.conflicts else ExitCode.READY)

    @app.command()
    def init(
        path: Path = typer.Argument(Path(), help="Project root."),
        write: bool = typer.Option(False, "--write", help="Write the files after review."),
        force: bool = typer.Option(False, "--overwrite", help="Allow overwriting."),
        as_json: bool = JsonOption,
    ) -> None:
        """Scaffold this project's devrepro setup: policy, hook and CI job.

        Prints everything first and writes nothing without `--write`, which is
        the same contract `generate` uses: a draft you review is useful, a file
        that appeared in your repository unannounced is not.

        The generated policy is derived from what the project already declares,
        so it starts as a description of reality rather than an aspiration
        nobody can meet.
        """
        from devrepro.generators import generate_devrepro_toml, write_generated
        from devrepro.project.detectors import detect_requirements
        from devrepro.project.policy import POLICY_FILENAME

        requirements = detect_requirements(path)
        runtimes = {
            r.name: r.spec
            for r in requirements
            if r.kind.value == "runtime" and r.spec not in ("", "*")
        }
        env_names = tuple(r.name for r in requirements if r.kind.value == "env-name")
        needs_docker = any(r.ecosystem == "container" for r in requirements)

        policy = generate_devrepro_toml(runtimes, env_names, require_docker=needs_docker)
        artifacts = {
            POLICY_FILENAME: policy,
            ".pre-commit-config.devrepro.yaml": _PRECOMMIT_SNIPPET,
            ".github/workflows/devrepro.yml": _WORKFLOW_SNIPPET,
        }

        written: list[dict[str, object]] = []
        for name, content in artifacts.items():
            target = path / name
            if write:
                result = write_generated(target, content, allow_overwrite=force)
                written.append(
                    {
                        "path": result.path,
                        "written": not result.requires_review or force,
                        "existed": result.existed,
                    }
                )
            else:
                written.append({"path": str(target), "written": False, "existed": target.exists()})

        if as_json:
            emit({"artifacts": written, "policy": policy}, True)
        else:
            for item in written:
                state = (
                    "written"
                    if item["written"]
                    else ("exists - not overwritten" if item["existed"] else "preview only")
                )
                typer.echo(f"  {item['path']}  [{state}]")
            if not write:
                typer.echo("")
                typer.echo(policy)
                typer.echo(
                    "Preview only. Re-run with --write to create these "
                    "(existing files are never overwritten without --overwrite)."
                )
        raise typer.Exit(ExitCode.READY)

    @app.command("ci-diff")
    def ci_diff_cmd(
        path: Path = typer.Argument(Path(), help="Repository root."),
        json_out: bool = JsonOption,
    ) -> None:
        """Compare CI-declared toolchains with the local machine."""
        from devrepro.project.ci_parsers import collect_ci_toolchains, local_vs_ci_diff

        ci = collect_ci_toolchains(path)
        local_versions = local_tool_versions()
        rows = local_vs_ci_diff(ci, local_versions)
        if json_out:
            emit(
                {
                    "ci_toolchains": [
                        {"tool": t.tool, "spec": t.spec, "source_file": t.source_file} for t in ci
                    ],
                    "rows": rows,
                },
                True,
            )
        else:
            typer.echo(f"CI toolchains found: {len(ci)}")
            for r in rows:
                # Marks and colours are looked up with a default: a new status
                # from local_vs_ci_diff must not crash the human-readable path.
                # "bright_black" is click's grey; "grey50" is a Rich name click
                # rejects, and it raised TypeError for every ci-absent row.
                mark = {
                    "match": "+",
                    "mismatch": "!",
                    "unknown-local": "?",
                    "wildcard": "~",
                    "ci-absent": "-",
                }.get(r["status"], "*")
                color = {
                    "match": "green",
                    "mismatch": "red",
                    "unknown-local": "yellow",
                    "wildcard": "yellow",
                    "ci-absent": "bright_black",
                }.get(r["status"], "white")
                typer.secho(
                    f"  [{mark}] {r['tool']}: CI={r['ci_spec']} local={r['local_version']}"
                    f" — {r['detail']}",
                    fg=color,
                )
        bad = any(r["status"] == "mismatch" for r in rows)
        raise typer.Exit(ExitCode.READY_WITH_WARNINGS if bad else ExitCode.READY)

    @app.command()
    def generate(
        what: str = typer.Argument(..., help="devrepro-toml | mise | asdf | devcontainer"),
        path: Path = typer.Argument(Path(), help="Project root."),
        write: bool = typer.Option(
            False, "--write", help="Write after review (refuses to overwrite)."
        ),
        force_overwrite: bool = typer.Option(
            False, "--overwrite", help="Explicitly allow overwrite."
        ),
        json_out: bool = JsonOption,
    ) -> None:
        """Generate reviewable environment-config drafts from detected requirements."""
        from devrepro.generators import (
            generate_devcontainer,
            generate_devrepro_toml,
            generate_tool_versions,
            write_generated,
        )
        from devrepro.project.detectors import detect_requirements

        reqs = detect_requirements(path)
        requirements = {r.name: r.spec for r in reqs if r.spec not in ("*", "")}
        env_names = tuple(sorted({r.name for r in reqs if r.kind.value == "env-name"}))
        builders: dict[str, Callable[[], str]] = {
            "devrepro-toml": lambda: generate_devrepro_toml(requirements, env_names),
            "mise": lambda: generate_tool_versions(requirements, style="mise"),
            "asdf": lambda: generate_tool_versions(requirements, style="asdf"),
            "devcontainer": generate_devcontainer,
        }
        builder = builders.get(what)
        if builder is None:
            typer.secho(f"unknown target {what!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(ExitCode.USAGE_ERROR)
        content = builder()
        filenames = {
            "devrepro-toml": ".devrepro.toml",
            "mise": ".mise.toml",
            "asdf": ".tool-versions",
            "devcontainer": ".devcontainer/devcontainer.json",
        }
        target = path / filenames[what]
        if not write:
            emit({"target": str(target), "content": content, "written": False}, json_out)
            if not json_out:
                typer.echo(content)
                typer.echo(
                    "[grey50]Preview only. Re-run with --write to create "
                    "(existing files are never overwritten without --overwrite).[/grey50]"
                )
            raise typer.Exit(ExitCode.READY)
        result = write_generated(target, content, allow_overwrite=force_overwrite)
        emit(
            {
                "target": result.path,
                "written": True,
                "requires_review": result.requires_review,
                "diff": result.diff or None,
            },
            json_out,
        )
        if not json_out:
            if result.diff:
                typer.echo(result.diff)
            typer.echo(f"wrote {result.path}")
        raise typer.Exit(ExitCode.READY)

    @app.command("profile")
    def profile_cmd(
        path: Path = typer.Argument(Path(), help="Project root."),
        as_json: bool = JsonOption,
    ) -> None:
        """Readiness profile + explainable reproducibility maturity score."""
        from devrepro.project.profiles import detect_profile, score_maturity

        prof = detect_profile(path)
        score = score_maturity(path)
        payload = {
            "profile": prof.profile,
            "confidence": round(prof.confidence, 2),
            "signals": list(prof.signals),
            "maturity": {
                "total": score.total,
                "possible": score.possible,
                "percent": score.percent,
                "factors": [
                    {"name": f.name, "earned": f.earned, "weight": f.weight, "detail": f.detail}
                    for f in score.factors
                ],
                "explanation": score.explanation(),
            },
        }
        emit(payload, as_json)
        raise typer.Exit(ExitCode.READY)

    @app.command("baseline")
    def baseline_cmd(
        action: str = typer.Argument(..., help="create | diff"),
        baseline_path: Path = typer.Option(
            Path(".devrepro-baseline.json"), "--file", help="Baseline manifest path."
        ),
        as_json: bool = JsonOption,
    ) -> None:
        """Create a project baseline or diff this machine against it."""
        from devrepro.snapshots.baseline import diff_against_baseline, load_baseline, new_baseline

        if action == "create":
            from devrepro.project.detectors import detect_requirements
            from devrepro.snapshots.baseline import save_baseline

            reqs = detect_requirements(Path())
            # runtime pins only; lockfile markers, wildcards and CI-only pins
            # (ci:*) are excluded — CI toolchains are not dev-machine requirements
            tools = {
                r.name: r.spec
                for r in reqs
                if r.kind.value == "runtime"
                and r.spec not in ("*", "")
                and not r.name.startswith("ci:")
            }
            env_names_t = tuple(sorted({r.name for r in reqs if r.ecosystem == "env"}))
            b = new_baseline(str(Path().resolve().name), tools, env_names_t)
            save_baseline(b, baseline_path)
            emit(
                {"created": str(baseline_path), "baseline_id": b.baseline_id, **b.as_dict()},
                as_json,
            )
            raise typer.Exit(ExitCode.READY)
        if action == "diff":
            b = load_baseline(baseline_path)
            import os

            machine_tools = local_tool_versions()
            env_names: set[str] = {name for name in b.required_env_names if name in os.environ}
            docker_ok = False
            try:
                from devrepro.core.runner import SubprocessRunner

                res = SubprocessRunner().run(("docker", "info"), timeout=10.0)
                docker_ok = res.returncode == 0
            except Exception:
                docker_ok = False
            diff = diff_against_baseline(b, machine_tools, env_names, docker_ok)
            emit(diff.as_dict(), as_json)
            raise typer.Exit(ExitCode.BLOCKED if diff.blockers else ExitCode.READY)
        typer.echo(f"unknown baseline action: {action!r} (use create|diff)", err=True)
        raise typer.Exit(ExitCode.USAGE_ERROR)


#: A pre-commit hook that gates on the *environment contract*, not on ambient
#: machine state. `devrepro guard` deliberately is not used here: it fails on
#: any machine-wide blocker, so a stopped Docker daemon would block every
#: commit and the hook would be removed within a week.
_PRECOMMIT_SNIPPET = """# Add these to your .pre-commit-config.yaml.
repos:
  - repo: local
    hooks:
      - id: devrepro-check
        name: devrepro policy check
        entry: devrepro check --policy .devrepro.toml --quiet
        language: system
        pass_filenames: false
        # Runs only when the environment contract itself changes.
        files: >-
          (?x)^(
            \\.devrepro\\.toml|
            pyproject\\.toml|package\\.json|go\\.mod|Cargo\\.toml|
            .*\\.lock|.*lock\\.json|.*lock\\.yaml|
            \\.github/workflows/.*\\.ya?ml
          )$
"""

_WORKFLOW_SNIPPET = """# Generated by `devrepro init` - REVIEW BEFORE COMMITTING.
name: Environment preflight

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  preflight:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: webdevsamran/devrepro-doctor/action@main
        with:
          command: preflight
          policy: .devrepro.toml
"""
