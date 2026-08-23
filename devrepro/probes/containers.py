"""Container doctor probe: Docker/Podman CLI presence, daemon health,
compose availability, kubectl. Classifies daemon failures precisely.
"""

from __future__ import annotations

import re

from devrepro.core.models import ContainerState, Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["ContainerProbe"]


def _classify_daemon_error(stderr: str) -> str:
    s = stderr.lower()
    if "cannot connect" in s or "connection refused" in s or "error during connect" in s:
        return "daemon-unreachable"
    if "permission denied" in s or "access is denied" in s:
        return "daemon-permission"
    if "pipe" in s and "docker" in s:
        return "daemon-pipe-missing"
    if "wsl" in s:
        return "docker-wsl-backend-error"
    return "daemon-error"


class ContainerProbe(Probe):
    id = "containers/doctor"
    version = "1"

    def run(self) -> ProbeResult:
        r = self.ctx.runner
        errors: list[str] = []
        findings = []

        docker_cli_version: str | None = None
        res = r.run(("docker", "--version"), timeout=10)
        if res.ok:
            m = re.search(r"Docker version ([\w.\-]+)", res.stdout)
            docker_cli_version = m.group(1) if m else None

        daemon_ok = False
        if docker_cli_version:
            info = r.run(("docker", "info", "--format", "{{.ServerVersion}}"), timeout=15)
            if info.ok and info.stdout.strip():
                daemon_ok = True
            else:
                kind = _classify_daemon_error(info.stderr or info.stdout)
                errors.append(f"docker daemon: {kind}")
                findings.append(
                    self.finding(
                        f"containers/docker-{kind}",
                        FindingState.BLOCKED,
                        f"Docker CLI {docker_cli_version} present but daemon unreachable ({kind}).",
                        evidence=(
                            self.cmd_evidence(("docker", "info"), (info.stderr or "")[:500]),
                        ),
                        detected=docker_cli_version,
                        component="docker",
                        remediation_hint="Start Docker Desktop / the docker service, then re-run "
                        "`devrepro doctor`. This blocks any container-based build.",
                    )
                )
        elif res.not_found:
            findings.append(
                self.finding(
                    "containers/docker-missing",
                    FindingState.INFO,
                    "Docker CLI not found on PATH.",
                    evidence=(
                        Evidence(
                            source="command", command=("docker", "--version"), excerpt="not found"
                        ),
                    ),
                    component="docker",
                )
            )

        podman_version: str | None = None
        pres = r.run(("podman", "--version"), timeout=10)
        if pres.ok:
            m = re.search(r"podman version ([\w.\-]+)", pres.stdout)
            podman_version = m.group(1) if m else None

        compose_version: str | None = None
        cres = r.run(("docker", "compose", "version", "--short"), timeout=10)
        if cres.ok:
            compose_version = cres.stdout.strip()
        else:
            cres2 = r.run(("docker-compose", "--version"), timeout=10)
            if cres2.ok:
                m = re.search(r"(\d+\.\d+[\w.\-]*)", cres2.stdout)
                compose_version = m.group(1) if m else None

        kubectl_version: str | None = None
        kres = r.run(("kubectl", "version", "--client=true", "-o", "json"), timeout=10)
        if kres.ok:
            m = re.search(r'"gitVersion":\s*"v([\w.\-]+)"', kres.stdout)
            kubectl_version = m.group(1) if m else None
        else:
            kres2 = r.run(("kubectl", "version", "--client"), timeout=10)
            if kres2.ok:
                m = re.search(r"v?Client Version.*?v([\w.\-]+)", kres2.stdout)
                kubectl_version = m.group(1) if m else None

        state = ContainerState(
            docker_cli_version=docker_cli_version,
            docker_daemon_ok=daemon_ok,
            podman_version=podman_version,
            compose_version=compose_version,
            kubectl_version=kubectl_version,
            errors=tuple(errors),
        )

        if state.docker_daemon_ok:
            findings.append(
                self.finding(
                    "containers/healthy",
                    FindingState.PASS,
                    f"Docker healthy: CLI {docker_cli_version}, daemon responding.",
                    evidence=(self.cmd_evidence(("docker", "info"), "server responded"),),
                    component="docker",
                )
            )

        return ProbeResult(
            self.id, findings=tuple(findings), data={"state": state.model_dump(mode="json")}
        )
