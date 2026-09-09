"""What could an agent reach from here, before it starts?

2026 produced real, attributable damage from coding agents operating in
environments nobody had checked: a production database and its backups deleted
in nine seconds, a platform's data wiped, a thirteen-hour outage after an agent
chose to delete and recreate an environment. The published post-mortems name
the same causes each time -- production and development blurred together,
permissions too broad, approval arriving too late.

Those are environment-verification problems, and they are answerable before an
agent takes its first action. This module answers them.

Two rules shape everything here. Credentials are reported **by name only** and
never read, which is the same promise `devrepro env` makes. And nothing is
mutated, including the git index: the checks shell out to read-only plumbing.

This is not a safety guarantee. It is a briefing: an honest account of what is
reachable, so a human decides what to do about it rather than finding out
afterwards.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from devrepro.core.runner import CommandRunner, SubprocessRunner
from devrepro.privacy.gate import looks_like_credential_name

__all__ = [
    "PRODUCTION_MARKERS",
    "BlastRadius",
    "Exposure",
    "assess_blast_radius",
]

#: Values that mark an environment variable as pointing at production. Matched
#: case-insensitively against the *value*, not the name.
PRODUCTION_MARKERS = ("prod", "production", "live", "prd")

#: Variables whose value naming a production environment matters. Deliberately
#: short: this is about deployment targets, not every variable that mentions a
#: word.
_ENV_TARGET_VARS = (
    "NODE_ENV",
    "RAILS_ENV",
    "DJANGO_SETTINGS_MODULE",
    "ASPNETCORE_ENVIRONMENT",
    "APP_ENV",
    "ENVIRONMENT",
    "DEPLOY_ENV",
    "STAGE",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "GOOGLE_CLOUD_PROJECT",
    "AZURE_SUBSCRIPTION_ID",
    "VERCEL_ENV",
    "FLY_APP_NAME",
)

#: Credential-shaped names come from the privacy module, so this assessment,
#: the env probe and the env-var analysis all agree on what counts. Writing a
#: third pattern here was the first instinct and the wrong one: it flagged
#: `CLAUDE_CODE_HOST_SESSION_ID`, which is an identifier, not a credential.

#: Files whose presence means a cloud CLI is already authenticated, so an agent
#: inherits that authority without needing a credential in the environment.
_AMBIENT_CREDENTIAL_FILES = (
    (".aws/credentials", "AWS CLI credentials"),
    (".config/gcloud/credentials.db", "gcloud credentials"),
    (".azure/msal_token_cache.json", "Azure CLI token cache"),
    (".kube/config", "Kubernetes cluster credentials"),
    (".docker/config.json", "Docker registry credentials"),
    (".npmrc", "npm registry token"),
    (".pypirc", "PyPI upload credentials"),
)


@dataclass(frozen=True)
class Exposure:
    """One thing an agent could reach, and why it matters."""

    kind: str
    severity: str  # "high" | "medium" | "info"
    summary: str
    detail: str
    evidence: str | None = None


@dataclass(frozen=True)
class BlastRadius:
    """The full briefing."""

    root: str
    exposures: tuple[Exposure, ...] = ()
    uncommitted_files: int = 0
    unpushed_commits: int = 0
    credential_names: tuple[str, ...] = field(default=())

    @property
    def highest_severity(self) -> str:
        for level in ("high", "medium", "info"):
            if any(e.severity == level for e in self.exposures):
                return level
        return "none"


def assess_blast_radius(
    root: Path | str, *, env: dict[str, str] | None = None, runner: CommandRunner | None = None
) -> BlastRadius:
    """Assess what an agent starting in ``root`` could reach."""
    root = Path(root)
    env = dict(os.environ) if env is None else env
    runner = runner or SubprocessRunner()

    exposures: list[Exposure] = []
    uncommitted, unpushed = _git_state(root, runner, exposures)
    credential_names = _credential_exposure(env, exposures)
    _production_exposure(env, runner, exposures)
    _ambient_credentials(exposures)
    _privilege_exposure(exposures)

    return BlastRadius(
        root=str(root),
        exposures=tuple(exposures),
        uncommitted_files=uncommitted,
        unpushed_commits=unpushed,
        credential_names=tuple(credential_names),
    )


def _git_state(root: Path, runner: CommandRunner, exposures: list[Exposure]) -> tuple[int, int]:
    """Work an agent could destroy that is not recoverable from a remote.

    `git status --porcelain` and `rev-list` are read-only plumbing; nothing
    here touches the index.
    """
    status = runner.run(("git", "-C", str(root), "status", "--porcelain"), timeout=15)
    if not status.ok:
        return 0, 0

    changed = [line for line in status.stdout.splitlines() if line.strip()]
    if changed:
        exposures.append(
            Exposure(
                kind="uncommitted-work",
                severity="medium" if len(changed) < 20 else "high",
                summary=f"{len(changed)} uncommitted change(s) in the working tree.",
                detail="An agent that resets, checks out or cleans will destroy work "
                "that exists nowhere else. Commit or stash before handing the "
                "repository over.",
                evidence=f"{len(changed)} entries from `git status --porcelain`",
            )
        )

    unpushed = 0
    rev = runner.run(
        ("git", "-C", str(root), "rev-list", "--count", "@{upstream}..HEAD"), timeout=15
    )
    if rev.ok and rev.stdout.strip().isdigit():
        unpushed = int(rev.stdout.strip())
        if unpushed:
            exposures.append(
                Exposure(
                    kind="unpushed-commits",
                    severity="medium",
                    summary=f"{unpushed} commit(s) not pushed to the upstream branch.",
                    detail="These exist only on this machine. A hard reset or a "
                    "force-push by an agent loses them.",
                    evidence="git rev-list --count @{upstream}..HEAD",
                )
            )
    return len(changed), unpushed


def _credential_exposure(env: dict[str, str], exposures: list[Exposure]) -> list[str]:
    """Credential-shaped variables an agent's subprocesses would inherit.

    Names only. The values are never read, which is what makes this safe to
    print, paste into an issue, or hand to the agent itself.
    """
    names = sorted(n for n in env if looks_like_credential_name(n))
    if names:
        exposures.append(
            Exposure(
                kind="inherited-credentials",
                severity="high" if len(names) > 3 else "medium",
                summary=f"{len(names)} credential-shaped variable(s) in this environment.",
                detail="Every subprocess an agent starts inherits these. Anything it "
                "runs -- a build script, a test, a package postinstall -- can use "
                "them. Values are never read by devrepro; only the names are listed.",
                evidence=", ".join(names[:8]),
            )
        )
    return names


def _production_exposure(
    env: dict[str, str], runner: CommandRunner, exposures: list[Exposure]
) -> None:
    """Is this shell pointed at something that is not a development target?"""
    pointing: list[str] = []
    for var in _ENV_TARGET_VARS:
        value = env.get(var)
        if value and any(marker in value.lower() for marker in PRODUCTION_MARKERS):
            pointing.append(f"{var}={value}")

    if pointing:
        exposures.append(
            Exposure(
                kind="production-target",
                severity="high",
                summary="This shell is configured against a production target.",
                detail="An agent inherits this. A command that would be harmless "
                "against a development environment is not harmless here -- this is "
                "the configuration behind the published incidents where an agent "
                "deleted a production database.",
                evidence="; ".join(pointing),
            )
        )

    context = runner.run(("kubectl", "config", "current-context"), timeout=10)
    if context.ok and context.stdout.strip():
        name = context.stdout.strip()
        is_prod = any(marker in name.lower() for marker in PRODUCTION_MARKERS)
        exposures.append(
            Exposure(
                kind="kubernetes-context",
                severity="high" if is_prod else "info",
                summary=f"kubectl is pointed at {name!r}.",
                detail="Any kubectl an agent runs goes to this cluster."
                + (
                    " The context name suggests production."
                    if is_prod
                    else " The name does not look like production, but confirm it."
                ),
                evidence="kubectl config current-context",
            )
        )


def _ambient_credentials(exposures: list[Exposure]) -> None:
    """Authority an agent inherits without any environment variable at all.

    A logged-in cloud CLI is more dangerous than a token in the environment,
    because nothing in the shell shows it is there.
    """
    home = Path.home()
    present = [label for rel, label in _AMBIENT_CREDENTIAL_FILES if (home / rel).exists()]
    if present:
        exposures.append(
            Exposure(
                kind="ambient-credentials",
                severity="medium",
                summary=f"{len(present)} authenticated CLI credential store(s) on this machine.",
                detail="An agent does not need a token in the environment to use "
                "these; the CLI reads them from disk. Nothing in the shell reveals "
                "that the authority is present.",
                evidence=", ".join(present),
            )
        )


def _privilege_exposure(exposures: list[Exposure]) -> None:
    """Is this process running with more authority than a developer needs?"""
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        exposures.append(
            Exposure(
                kind="elevated-privileges",
                severity="high",
                summary="Running as root.",
                detail="An agent's mistakes are unbounded by file permissions here. "
                "There is rarely a reason to develop as root, and every reason not "
                "to hand root to an autonomous process.",
                evidence="os.geteuid() == 0",
            )
        )
