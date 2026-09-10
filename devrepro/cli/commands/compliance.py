"""Compliance commands: attest, evidence, advisories.

Three commands that all answer a question somebody outside the team asked.
They share a shape: produce a document, say what it does *not* claim, and stop
short of the irreversible step. `attest` prints the cosign command instead of
running it; `evidence` marks controls out of scope instead of green;
`advisories` warns and never blocks.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- typer reads this annotation at runtime

import typer

from devrepro.cli.common import JsonOption, PolicyOption, emit, load_policy_or_none, secho
from devrepro.core.exit_codes import ExitCode


def register(app: typer.Typer) -> None:
    """Attach compliance commands to the root app."""

    @app.command()
    def attest(  # noqa: PLR0917 -- CLI options, not a call signature
        subject: Path = typer.Argument(
            ...,
            exists=True,
            readable=True,
            help="The file this statement is about, usually a snapshot.",
        ),
        kind: str = typer.Option(
            "environment",
            "--kind",
            help="environment | reproduction | provenance",
        ),
        output: Path | None = typer.Option(None, "-o", "--output"),
        environment_digest: str | None = typer.Option(
            None,
            "--environment-digest",
            help="For --kind reproduction: the sha256 of the environment attestation.",
        ),
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Build an in-toto attestation about an environment. Signs nothing."""
        from devrepro.cli.pipeline import run_scan
        from devrepro.compliance.attest import (
            build_environment_statement,
            build_reproduction_statement,
            build_slsa_provenance,
            cosign_command,
            render_statement,
            subject_for_file,
        )

        if kind not in {"environment", "reproduction", "provenance"}:
            secho(f"unknown --kind {kind!r}: environment | reproduction | provenance", fg="red")
            raise typer.Exit(ExitCode.USAGE_ERROR)
        if kind == "reproduction" and not environment_digest:
            secho(
                "--kind reproduction needs --environment-digest: the point of the "
                "statement is the link between the artefact and the environment.",
                fg="red",
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)

        report = run_scan(policy=load_policy_or_none(policy_path))
        subject_doc = subject_for_file(subject)

        if kind == "environment":
            statement = build_environment_statement(report, subject_doc)
        elif kind == "reproduction":
            statement = build_reproduction_statement(
                report,
                subject_doc,
                environment_digest=environment_digest or "",
                reproduced=True,
            )
        else:
            statement = build_slsa_provenance(
                subject_doc,
                builder_id=f"devrepro/{report.devrepro_version}",
                started_at=report.created_at.isoformat(),
                external_parameters={"subject": subject.name},
            )

        rendered = render_statement(statement)
        if output is not None:
            output.write_text(rendered, encoding="utf-8")

        if json_out:
            emit(statement, True)
        else:
            typer.echo(rendered if output is None else f"wrote {output}")
            typer.echo("")
            typer.echo("To sign it (this contacts Sigstore and writes a public log entry):")
            typer.echo("  " + " ".join(cosign_command(output or "statement.json", subject)))
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def evidence(
        framework: str | None = typer.Option(
            None, "--framework", help="cra | ssdf | slsa; omit for all."
        ),
        licenses: bool = typer.Option(
            False, "--licenses", help="Toolchain license inventory instead of controls."
        ),
        output: Path | None = typer.Option(None, "-o", "--output"),
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Map this machine's scan onto named controls, or inventory tool licenses."""
        import json as _json

        from devrepro.cli.pipeline import run_scan
        from devrepro.compliance.controls import build_evidence_pack, frameworks
        from devrepro.compliance.licenses import toolchain_licenses

        if framework is not None and framework not in frameworks():
            secho(
                f"unknown --framework {framework!r}: " + " | ".join(frameworks()),
                fg="red",
            )
            raise typer.Exit(ExitCode.USAGE_ERROR)

        report = run_scan(policy=load_policy_or_none(policy_path))
        payload = (
            toolchain_licenses(report)
            if licenses
            else build_evidence_pack(report, framework=framework)
        )

        if output is not None:
            output.write_text(_json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        if json_out:
            emit(payload, True)
        elif licenses:
            typer.echo(payload["scope"])
            typer.echo("")
            for row in payload["tools"]:
                version = row.get("version") or "?"
                typer.echo(f"  {row['tool']} {version}: {row['spdx']} [{row['obligation']}]")
            if payload["unknown"]:
                typer.echo("")
                typer.echo("  not in the table: " + ", ".join(payload["unknown"]))
        else:
            typer.echo(payload["scope"])
            typer.echo("")
            for row in payload["controls"]:
                typer.echo(f"  [{row['status']}] {row['id']} - {row['title']}")
                typer.echo(f"      {row['detail']}")
                # The reason a control is declined is the substance of
                # declining it. Printing the status without it turns a
                # deliberate boundary back into an unexplained gap.
                if row.get("outOfScopeBecause"):
                    typer.echo(f"      Why: {row['outOfScopeBecause']}")
        raise typer.Exit(ExitCode.READY)

    @app.command()
    def advisories(
        db: Path | None = typer.Option(
            None, "--db", help="An advisory bundle to use instead of the bundled seed."
        ),
        trust_unsigned: bool = typer.Option(
            False,
            "--trust-unsigned",
            help="Accept an external bundle with no signature beside it.",
        ),
        json_out: bool = JsonOption,
        policy_path: Path | None = PolicyOption,
    ) -> None:
        """Check installed toolchain versions against an offline advisory set."""
        import os

        from devrepro.cli.pipeline import run_scan
        from devrepro.compliance.advisories import AdvisoryError, affected_tools, load_bundle

        key_text = os.environ.get("DEVREPRO_ADVISORY_KEY", "")
        try:
            bundle = load_bundle(
                db,
                key=key_text.encode("utf-8") if key_text else None,
                trust_unsigned=trust_unsigned,
            )
        except AdvisoryError as exc:
            secho(str(exc), fg="red")
            raise typer.Exit(ExitCode.USAGE_ERROR) from exc

        report = run_scan(policy=load_policy_or_none(policy_path))
        installed = report.active_versions()
        hits = affected_tools(installed, bundle)

        payload = {
            "bundle": {
                "source": bundle.source,
                "published": bundle.published,
                "signed": bundle.signed,
                "covers": list(bundle.covers),
            },
            "checked": sorted(installed),
            "affected": [
                {"tool": name, "version": version, **advisory.as_dict()}
                for name, version, advisory in hits
            ],
        }

        if json_out:
            emit(payload, True)
        else:
            typer.echo(
                f"Advisory set: {bundle.source}, reviewed {bundle.published}, "
                f"covering {', '.join(bundle.covers) or 'nothing'}."
            )
            uncovered = sorted(set(installed) - set(bundle.covers))
            if uncovered:
                typer.echo(
                    "No advisory data for: "
                    + ", ".join(uncovered)
                    + " - that is silence, not a clean result."
                )
            typer.echo("")
            if not hits:
                typer.echo("Nothing in this set matches the installed versions.")
            for name, version, advisory in hits:
                secho(
                    f"  [{advisory.severity}] {name} {version} - {advisory.id}",
                    fg="yellow",
                )
                typer.echo(f"      {advisory.summary}")
                typer.echo(f"      fixed in {', '.join(advisory.fixed)} · {advisory.reference}")

        # Warnings, never a block. The branch-fallback in `is_affected` errs
        # toward reporting, and a check that can be wrong in the loud direction
        # has no business failing anybody's build.
        raise typer.Exit(ExitCode.READY_WITH_WARNINGS if hits else ExitCode.READY)
