"""CLI command modules — one per domain, registered onto a flat CLI surface.

Every module exposes a single ``register(app)`` hook that attaches its
commands to the root :class:`typer.Typer` application. Commands stay top-level
(``devrepro doctor``), while the implementation stays split by domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer


def register_all(app: typer.Typer) -> None:
    """Attach every domain module's commands to the root Typer app."""
    from devrepro.cli.commands import (
        diagnostics,
        environment,
        platform,
        project,
        remediation,
        reports,
        service,
        snapshots,
    )

    for module in (
        diagnostics,
        project,
        environment,
        snapshots,
        remediation,
        reports,
        platform,
        service,
    ):
        module.register(app)


__all__ = ["register_all"]
