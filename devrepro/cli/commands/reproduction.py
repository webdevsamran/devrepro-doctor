"""The `reproduce` command: a recipe somebody else can run, and the search tools.

`reproduce` rather than `generate`. `generate` already means "draft a config
from what I detected", which is a different job with a different failure mode,
and one verb doing both would leave them sharing a set of flags that half apply.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none, secho
from devrepro.core.exit_codes import ExitCode

_LOCKFILE_NAMES = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "requirements.txt",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
)


def register(app: typer.Typer) -> None:
    """Attach reproduction commands to the root app."""

    @app.command()
    def reproduce(  # noqa: PLR0917 -- CLI options, not a call signature
        path: Path = typer.Argument(Path(), help="Repository root."),
        failing_command: str | None = typer.Option(
            None,
            "--failing-command",
            help="The command that failed. Without it this drafts an environment, "
            "not a reproduction.",
        ),
        symptom: str | None = typer.Option(
            None, "--symptom", help="What failing looked like, so a reader can tell."
        ),
        emit_format: str = typer.Option(
            "dockerfile",
            "--emit",
            help="dockerfile | script | compose | devcontainer | nix | all",
        ),
        sandbox: str | None = typer.Option(
            None, "--sandbox", help="Emit for a sandbox instead: e2b | daytona | container-use."
        ),
        output_dir: Path | None = typer.Option(
            None, "-o", "--output", help="Write the files here instead of printing them."
        ),
        pin: bool = typer.Option(
            False,
            "--pin",
            help="OPT-IN: ask the container engine to resolve the base image to a digest.",
        ),
        check: bool = typer.Option(
            False,
            "--check",
            help="Verify a committed recipe still matches this project. Writes nothing.",
        ),
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Draft a container recipe that reproduces a reported failure. Runs nothing.

        The recipe is the artefact: reviewable, diffable, attachable to an issue.
        Building the image downloads gigabytes and running the failing command
        executes what the project told us to execute, so both stay the user's
        decision.

        Without `--failing-command` this drafts an environment and says so in
        the file's own header. What makes a recipe a *reproduction* is that it
        ends by running the thing that failed -- so when somebody fixes the
        cause, the recipe stops working, which is the signal anybody wants.

        `--pin` resolves the base image to an immutable digest, which needs a
        reachable container engine. It is opt-in for the same reason
        `network --allow-network` is: resolving a digest contacts a registry.
        """
        from devrepro.cli.pipeline import run_scan
        from devrepro.generators import resolve_image_digest
        from devrepro.reproduce import (
            EMIT_FORMATS,
            build_reproduction,
            render_adapter,
            render_compose,
            render_devcontainer,
            render_dockerfile,
            render_nix_flake,
            render_repro_script,
            strip_provenance,
        )

        if emit_format not in {*EMIT_FORMATS, "all"}:
            secho(
                f"unknown --emit {emit_format!r}: {', '.join([*EMIT_FORMATS, 'all'])}",
                fg="red",
                err=True,
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)

        report = run_scan(project_dir=path, policy=load_policy_or_none(policy_path))
        present = frozenset(name for name in _LOCKFILE_NAMES if (path / name).is_file())

        recipe = build_reproduction(
            report,
            failing_command=failing_command,
            expected_symptom=symptom,
            present_lockfiles=present,
        )

        if pin:
            digest = resolve_image_digest(recipe.base_image)
            if digest:
                recipe = dataclasses.replace(recipe, base_digest=digest)
            else:
                secho(
                    "Could not resolve a digest: no reachable container engine, or the "
                    "image is not published. The recipe stays on a mutable tag and says "
                    "so in its own header.",
                    fg="yellow",
                    err=True,
                )

        if sandbox is not None:
            try:
                filename, content = render_adapter(sandbox, recipe)
            except ValueError as exc:
                secho(str(exc), fg="red", err=True)
                raise typer.Exit(ExitCode.USAGE_ERROR) from exc
            files = {filename: content}
        else:
            renderers = {
                "dockerfile": ("Dockerfile.repro", render_dockerfile),
                "script": ("repro.sh", render_repro_script),
                "compose": ("compose.repro.yaml", render_compose),
                "devcontainer": (".devcontainer/devcontainer.json", render_devcontainer),
                "nix": ("flake.nix", render_nix_flake),
            }
            chosen = EMIT_FORMATS if emit_format == "all" else (emit_format,)
            files = {renderers[name][0]: renderers[name][1](recipe) for name in chosen}

        if check:
            # The same shape as `generate_schemas.py --check`: regenerate and
            # compare, so a committed recipe that has silently stopped
            # describing the project fails a CI job instead of failing a
            # maintainer six months from now. Writes nothing either way.
            base = output_dir or path
            stale: list[str] = []
            missing: list[str] = []
            for name, content in files.items():
                target = base / name
                if not target.is_file():
                    missing.append(str(target))
                elif strip_provenance(target.read_text(encoding="utf-8")) != strip_provenance(
                    content
                ):
                    # Compared without the timestamp lines: the file records
                    # when it was generated, and a check that treated that as
                    # content could only ever fail.
                    stale.append(str(target))

            payload = {"checked": sorted(files), "stale": stale, "missing": missing}
            if json_out:
                emit(payload, True)
            elif stale or missing:
                for name in missing:
                    secho(f"missing  {name}", fg="red", err=True)
                for name in stale:
                    secho(f"stale    {name}", fg="red", err=True)
                typer.echo(
                    "Re-run `devrepro reproduce` without --check to refresh them.",
                    err=True,
                )
            else:
                typer.echo(f"ok     {len(files)} recipe file(s) still match this project")
            raise typer.Exit(ExitCode.READY_WITH_WARNINGS if (stale or missing) else ExitCode.READY)

        if output_dir is not None:
            for name, content in files.items():
                target = output_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

        if json_out:
            emit({"recipe": recipe.as_dict(), "files": files}, True)
        elif output_dir is not None:
            for name in files:
                typer.echo(f"wrote {output_dir / name}")
            if not recipe.reproduces:
                typer.echo("")
                typer.echo(
                    "No --failing-command was given, so this is an environment draft "
                    "rather than a reproduction."
                )
        else:
            for name, content in files.items():
                typer.echo(f"--- {name} ---")
                typer.echo(content)
        raise typer.Exit(ExitCode.READY)

    @app.command("repro-rate")
    def repro_rate(
        record: str | None = typer.Option(
            None,
            "--record",
            help="Record an outcome: reproduced | not-reproduced | different-failure "
            "| could-not-build | precondition-unmet",
        ),
        note: str = typer.Option("", "--note", help="What the attempt was for."),
        json_out: bool = JsonOption,
    ) -> None:
        """How often reproductions actually work here. Local only; nothing is uploaded.

        Every tool in this space claims to reproduce environments and none
        publishes a rate, because the number is going to be disappointing -- a
        machine's state includes things no container carries. Publishing it
        anyway is more useful than implying 100% and letting every user
        discover otherwise separately.

        Recording is explicit: `--record` takes the verdict from the person who
        ran it. Nothing infers success from an exit code, because "the container
        ran" and "the failure reproduced" are different questions and only a
        person can answer the second.
        """
        from devrepro.reproduce.corpus import (
            OUTCOMES,
            Attempt,
            CorpusError,
            read_corpus,
            record_attempt,
            summarise,
        )
        from devrepro.snapshots.store import default_history_dir

        directory = default_history_dir()

        if record is not None:
            try:
                record_attempt(
                    directory,
                    Attempt(
                        outcome=record,
                        recorded_at=datetime.now(UTC).isoformat(),
                        note=note,
                    ),
                )
            except CorpusError as exc:
                secho(str(exc), fg="red", err=True)
                raise typer.Exit(ExitCode.USAGE_ERROR) from exc

        try:
            summary = summarise(read_corpus(directory))
        except CorpusError as exc:
            secho(str(exc), fg="red", err=True)
            raise typer.Exit(ExitCode.INTERNAL_ERROR) from exc

        if json_out:
            emit(summary.as_dict(), True)
        else:
            typer.echo(f"{summary.total} recorded attempt(s).")
            for outcome, count in sorted(summary.counts.items()):
                typer.echo(f"  {count:>4}  {outcome} - {OUTCOMES.get(outcome, '')}")
            typer.echo("")
            if summary.rate is None:
                typer.echo(summary.caveat)
            else:
                typer.echo(f"Reproduction rate: {summary.rate:.0%}")
                typer.echo(summary.caveat)
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def bisect(  # noqa: PLR0917 -- CLI options, not a call signature
        a: Path = typer.Argument(..., exists=True, help="Snapshot where it worked."),
        b: Path = typer.Argument(..., exists=True, help="Snapshot where it broke."),
        minimise: bool = typer.Option(
            False,
            "--minimise",
            help="Find the smallest failing SET rather than a single culprit.",
        ),
        plan: bool = typer.Option(
            False,
            "--plan",
            help="Print the candidate sets in order and exit, without asking anything.",
        ),
        max_verdicts: int = typer.Option(
            200, "--max-verdicts", help="Bound on --minimise; each verdict is a build."
        ),
        json_out: bool = JsonOption,
    ) -> None:
        """`git bisect` for a machine: narrow a forty-line diff to what matters.

        Everybody's instinct is to read an environment diff and pick the
        suspicious-looking line. That works when the cause is a runtime version
        and fails completely when it is a locale, a PATH order or a variable
        nobody thinks about. Bisection does not care what looks suspicious.

        **This applies nothing.** Applying an environment dimension means
        editing a PATH, installing a version or setting a variable on your
        machine, which is the whole class of action this project does not take
        unasked. It proposes a candidate set, you apply it and answer, and it
        halves the space -- the `git bisect` interface, because it is the one
        everybody already knows.

        `--minimise` answers the question bisection structurally cannot: when
        two changes are each harmless and break things only together, a bisect
        names one of them and is wrong in a way that reads as right.
        """
        from devrepro.diff.engine import diff_snapshots
        from devrepro.reproduce.bisect import Dimension, bisect_dimensions, minimise_dimensions
        from devrepro.snapshots.store import load_snapshot

        diff = diff_snapshots(load_snapshot(a), load_snapshot(b))
        dimensions = tuple(
            Dimension(
                name=f"{e.component}/{e.name}", working_value=e.a_value, broken_value=e.b_value
            )
            for e in diff.entries
            if e.classification.value != "same"
        )

        if not dimensions:
            emit({"dimensions": [], "detail": "The two snapshots do not differ."}, json_out)
            raise typer.Exit(ExitCode.READY)

        if plan:
            # The candidate sets, in order, for somebody automating the answers.
            # Emitted rather than executed for the same reason the rest is.
            payload = {
                "dimensions": [d.describe() for d in dimensions],
                "note": (
                    "Apply each candidate set to the working environment, then answer "
                    "whether the failure is present. The order adapts to your answers, "
                    "so this lists the dimensions rather than a fixed script."
                ),
            }
            emit(payload, json_out)
            raise typer.Exit(ExitCode.READY)

        typer.echo(f"{len(dimensions)} difference(s) between these snapshots.")
        typer.echo(
            "For each candidate, apply those differences to the WORKING environment "
            "and answer whether the failure appears. Nothing is applied for you."
        )
        typer.echo("")

        def ask(candidate: tuple[Dimension, ...]) -> bool:
            if not candidate:
                typer.echo("Candidate: nothing applied (the working environment as-is).")
            else:
                typer.echo(f"Candidate: apply {len(candidate)} difference(s):")
                for dimension in candidate:
                    typer.echo(f"  - {dimension.describe()}")
            return typer.confirm("  Does the failure appear?")

        outcome: dict[str, object]
        if minimise:
            outcome = minimise_dimensions(dimensions, ask, max_verdicts=max_verdicts).as_dict()
        else:
            found = bisect_dimensions(dimensions, ask)
            outcome = {
                "culprit": found.culprit.describe() if found.culprit else None,
                "verdicts": found.verdicts,
                "inconclusive_because": found.inconclusive_because,
                "trail": [
                    {"applied": list(names), "failed": failed} for names, failed in found.trail
                ],
            }

        typer.echo("")
        if json_out:
            emit(outcome, True)
        elif outcome.get("inconclusive_because"):
            secho(str(outcome["inconclusive_because"]), fg="yellow")
        elif minimise:
            typer.echo("Smallest set that still reproduces the failure:")
            minimal = outcome["minimal"]
            for line in minimal if isinstance(minimal, list) else []:
                typer.echo(f"  - {line}")
            if outcome["interacting"]:
                typer.echo("")
                typer.echo(
                    "More than one is needed together. A bisect would have named just "
                    "one of these, and been wrong in a way that reads as right."
                )
        else:
            typer.echo(f"Culprit: {outcome['culprit']}")
            typer.echo(f"({outcome['verdicts']} verdict(s))")
        raise typer.Exit(ExitCode.READY)
