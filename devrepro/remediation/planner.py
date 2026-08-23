"""Safe remediation planner and executor.

Safety model
------------
- Every remediation declares risk (SAFE/LOW/MEDIUM/HIGH), preconditions,
  exact intended changes, rollback guidance.
- ``plan`` is always a dry-run: nothing is executed.
- ``fix`` executes ONLY SAFE/LOW automatable steps, after explicit
  confirmation, with preconditions verified immediately before execution.
- Never uninstalls tools, modifies drivers, edits sensitive registry/system
  files, or deletes user data. MEDIUM/HIGH steps print instructions only.
"""

from __future__ import annotations

from collections.abc import Callable

from devrepro.core.errors import RemediationRefusedError
from devrepro.core.models import Finding, FindingState, Remediation, RiskLevel

__all__ = ["AUTOMATABLE_RISKS", "build_plan", "execute_plan"]

AUTOMATABLE_RISKS: frozenset[RiskLevel] = frozenset({RiskLevel.SAFE, RiskLevel.LOW})

Executor = Callable[[tuple[str, ...]], int]


def build_plan(findings: list[Finding]) -> list[Remediation]:
    """Derive remediation steps from findings. Conservative by design."""
    plan: list[Remediation] = []
    seen: set[str] = set()

    for f in findings:
        if f.state in (FindingState.PASS, FindingState.INFO):
            continue

        if f.rule_id == "path/duplicates":
            step = Remediation(
                id="rem/path-remove-duplicates",
                title="Remove duplicate PATH entries",
                risk=RiskLevel.SAFE,
                preconditions=("No running installer is modifying PATH",),
                changes=(
                    "Rewrite the user PATH variable keeping the first occurrence "
                    "of each entry, preserving order.",
                ),
                rollback="Restore PATH from the backup file written next to the change log.",
                automatable=True,
                finding_ids=(f.rule_id,),
            )
        elif f.rule_id == "path/dead-entries":
            step = Remediation(
                id="rem/path-remove-dead",
                title="Remove dead PATH entries",
                risk=RiskLevel.LOW,
                preconditions=("Entry does not exist on disk (verified at execution time)",),
                changes=("Remove PATH entries whose directories no longer exist.",),
                rollback="Restore PATH from the backup file written next to the change log.",
                automatable=True,
                finding_ids=(f.rule_id,),
            )
        elif f.rule_id.endswith("/version-mismatch") or f.rule_id.endswith("/missing"):
            tool = f.component or "tool"
            step = Remediation(
                id=f"rem/install-{tool}",
                title=f"Install/align {tool} to required range",
                risk=RiskLevel.MEDIUM,
                preconditions=(f"A package source for {tool} is reachable",),
                changes=(
                    f"Install {tool} within range {f.required or 'declared'} using a version "
                    "manager where available (pyenv/nvm/rustup/sdkman). DevRepro prints the "
                    "commands; it does not run installs automatically.",
                ),
                rollback="Version managers allow `switch` back to the previous version; "
                "system-wide installs must be rolled back manually.",
                automatable=False,
                finding_ids=(f.rule_id,),
            )
        elif f.rule_id.startswith("containers/docker-daemon"):
            step = Remediation(
                id="rem/start-docker-daemon",
                title="Start the Docker daemon",
                risk=RiskLevel.SAFE,
                preconditions=("Docker Desktop installed or docker.service present",),
                changes=(
                    "Start Docker Desktop (Windows/macOS) or systemctl start docker (Linux).",
                ),
                rollback="Stop the daemon again (`systemctl stop docker` / quit Docker Desktop).",
                automatable=False,
                finding_ids=(f.rule_id,),
            )
        elif f.rule_id == "wsl/no-default-distro":
            step = Remediation(
                id="rem/wsl-set-default",
                title="Set the default WSL distro",
                risk=RiskLevel.SAFE,
                preconditions=("At least one WSL distro registered",),
                changes=("Run `wsl --set-default <distro>` for the first registered distro.",),
                rollback="Run `wsl --set-default <previous>` (recorded in the change log).",
                automatable=True,
                finding_ids=(f.rule_id,),
            )
        elif f.rule_id == "network/clock-skew":
            step = Remediation(
                id="rem/enable-time-sync",
                title="Enable automatic time synchronization",
                risk=RiskLevel.LOW,
                preconditions=("Time service available (w32time/timedatectl)",),
                changes=("Enable NTP sync via OS settings; never touches TLS configuration.",),
                rollback="Disable automatic time sync again via OS settings.",
                automatable=False,
                finding_ids=(f.rule_id,),
            )
        else:
            continue

        if step.id not in seen:
            seen.add(step.id)
            plan.append(step)

    plan.sort(key=lambda r: {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}[r.risk.value])
    return plan


def execute_plan(
    plan: list[Remediation],
    *,
    confirmed: bool,
    executor: Executor,
    precondition_check: Callable[[Remediation], bool] | None = None,
) -> list[dict[str, str]]:
    """Execute automatable steps. Refuses unless explicitly confirmed."""
    if not confirmed:
        raise RemediationRefusedError(
            "Refusing to execute: no explicit confirmation given. "
            "`devrepro fix` requires --yes after reviewing `devrepro plan`."
        )
    results: list[dict[str, str]] = []
    for step in plan:
        if not step.automatable or step.risk not in AUTOMATABLE_RISKS:
            results.append({"id": step.id, "status": "skipped-manual"})
            continue
        if precondition_check is not None and not precondition_check(step):
            results.append({"id": step.id, "status": "skipped-preconditions"})
            continue
        for command in step.commands:
            rc = executor(command)
            results.append(
                {
                    "id": step.id,
                    "status": "executed" if rc == 0 else f"failed(rc={rc})",
                    "command": " ".join(command),
                }
            )
    return results
