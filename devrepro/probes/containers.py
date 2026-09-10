"""Container doctor probe: what is behind `docker`, and what shape it is in.

This began as a liveness check -- is a daemon responding -- which answers the
one container question nobody needs help with, because a dead daemon announces
itself the moment you try to use it. The questions that cost an afternoon are
which *engine* is answering, whether it is emulating a different architecture,
which cgroup version and storage driver it is using, and whether the disk it
builds on is full of layers nobody wants.

All of it is read from commands the daemon already answers. Nothing here
creates, removes or prunes anything: `docker system df` reports reclaimable
space and this tool reports it back, which is as far as a read-only diagnostic
goes. Pruning is the user's call and stays a copy-pasteable command.

Parsing lives in `devrepro.containers.engine` so it can be tested against
recorded output from machines none of us has.
"""

from __future__ import annotations

import json
import re

from devrepro.containers.engine import (
    LEGACY_STORAGE_DRIVERS,
    RUNTIME_CLIS,
    classify_endpoint,
    identify_backend,
    parse_docker_info,
    parse_system_df,
)
from devrepro.core.models import ContainerState, Evidence, Finding, FindingState
from devrepro.probes.base import Probe, ProbeResult
from devrepro.probes.helpers import resolve_all_on_path

__all__ = ["ContainerProbe"]

#: Reclaimable space worth mentioning. Below this it is noise -- every machine
#: that has ever built an image has a couple of gigabytes of layers -- and
#: above it, it is usually the reason a build died on "no space left".
_RECLAIMABLE_WARN_BYTES = 20 * 1000**3


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
        findings: list[Finding] = []

        docker_cli_version: str | None = None
        res = r.run(("docker", "--version"), timeout=10)
        if res.ok:
            m = re.search(r"Docker version ([\w.\-]+)", res.stdout)
            docker_cli_version = m.group(1) if m else None

        daemon_ok = False
        engine = None
        if docker_cli_version:
            # One call for everything. The previous version asked only for
            # `{{.ServerVersion}}`, which is the single least useful field in
            # the object it had to build anyway.
            info = r.run(("docker", "info", "--format", "{{json .}}"), timeout=15)
            if info.ok and info.stdout.strip():
                engine = parse_docker_info(info.stdout)
                daemon_ok = engine is not None and engine.server_version is not None
            if not daemon_ok:
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

        # --- which engine, and where ----------------------------------------
        #
        # `docker context inspect` answers whether or not the daemon is up, and
        # it is the only place that names the socket. The socket is read to
        # identify the backend and then discarded: a Colima path is
        # `unix:///Users/<name>/.colima/...`, and a snapshot is something
        # people share.
        context_name: str | None = None
        endpoint: str | None = None
        if docker_cli_version:
            ctx_res = r.run(("docker", "context", "inspect", "--format", "{{json .}}"), timeout=10)
            if ctx_res.ok:
                context_name, endpoint = _parse_context(ctx_res.stdout)

        backend = identify_backend(
            endpoint=endpoint,
            context_name=context_name,
            daemon_name=engine.name if engine else None,
            platform=self.ctx.platform,
        )

        other_runtimes = tuple(
            label for command, label in sorted(RUNTIME_CLIS.items()) if resolve_all_on_path(command)
        )

        buildx_version: str | None = None
        if docker_cli_version:
            bres = r.run(("docker", "buildx", "version"), timeout=10)
            if bres.ok:
                m = re.search(r"v?(\d+\.\d+[\w.\-]*)", bres.stdout)
                buildx_version = m.group(1) if m else None

        disk = None
        if daemon_ok:
            dres = r.run(("docker", "system", "df", "--format", "{{json .}}"), timeout=20)
            if dres.ok:
                disk = parse_system_df(dres.stdout)

        state = ContainerState(
            docker_cli_version=docker_cli_version,
            docker_daemon_ok=daemon_ok,
            podman_version=podman_version,
            compose_version=compose_version,
            kubectl_version=kubectl_version,
            errors=tuple(errors),
            backend=backend,
            endpoint_kind=classify_endpoint(endpoint),
            context_name=context_name,
            server_version=engine.server_version if engine else None,
            server_os=engine.server_os if engine else None,
            server_arch=engine.server_arch if engine else None,
            storage_driver=engine.storage_driver if engine else None,
            cgroup_version=engine.cgroup_version if engine else None,
            cgroup_driver=engine.cgroup_driver if engine else None,
            rootless=engine.rootless if engine else None,
            engine_cpus=engine.cpus if engine else None,
            engine_memory_bytes=engine.memory_bytes if engine else None,
            buildx_version=buildx_version,
            reclaimable_bytes=disk.reclaimable_bytes if disk else None,
            dangling_images=disk.dangling_images if disk else None,
            unused_volumes=disk.unused_volumes if disk else None,
            other_runtimes=other_runtimes,
        )

        findings.extend(self._depth_findings(state))

        if state.docker_daemon_ok:
            described = f"{backend} backend" if backend else "daemon responding"
            findings.append(
                self.finding(
                    "containers/healthy",
                    FindingState.PASS,
                    f"Docker healthy: CLI {docker_cli_version}, {described}.",
                    evidence=(self.cmd_evidence(("docker", "info"), "server responded"),),
                    component="docker",
                )
            )

        return ProbeResult(
            self.id, findings=tuple(findings), data={"state": state.model_dump(mode="json")}
        )

    def _depth_findings(self, state: ContainerState) -> list[Finding]:
        """Findings about how the engine is configured, not whether it is up."""
        out: list[Finding] = []
        evidence = (self.cmd_evidence(("docker", "info", "--format", "{{json .}}"), "engine info"),)

        # A host and a daemon on different architectures means qemu is doing the
        # work. The build succeeds, which is why this goes unnoticed, and takes
        # roughly an order of magnitude longer.
        host_arch = _normalise_arch(self.ctx.platform_info.arch)
        server_arch = _normalise_arch(state.server_arch)
        if host_arch and server_arch and host_arch != server_arch:
            out.append(
                self.finding(
                    "containers/arch-emulated",
                    FindingState.WARN,
                    f"Container engine reports {state.server_arch} on a {host_arch} host; "
                    "builds run under emulation.",
                    evidence=evidence,
                    detected=state.server_arch,
                    required=host_arch,
                    component="docker",
                    remediation_hint="Build for the host architecture, or pass an explicit "
                    "`--platform` so the emulation is at least deliberate. Emulated builds "
                    "are correct and roughly ten times slower.",
                )
            )

        if state.cgroup_version == "1":
            out.append(
                self.finding(
                    "containers/cgroup-v1",
                    FindingState.WARN,
                    "Container engine is using cgroup v1.",
                    evidence=evidence,
                    detected="v1",
                    required="v2",
                    component="docker",
                    remediation_hint="Memory and CPU limits behave differently under v1, so a "
                    "container that is OOM-killed in CI can pass here. Enable unified cgroups "
                    "on the host, or in Docker Desktop settings.",
                )
            )

        driver = (state.storage_driver or "").lower()
        if driver in LEGACY_STORAGE_DRIVERS:
            out.append(
                self.finding(
                    "containers/storage-driver-legacy",
                    FindingState.WARN,
                    f"Storage driver is {state.storage_driver}: {LEGACY_STORAGE_DRIVERS[driver]}.",
                    evidence=evidence,
                    detected=state.storage_driver,
                    required="overlay2",
                    component="docker",
                    remediation_hint="Switch the daemon to overlay2. Changing the storage "
                    "driver discards existing images and containers, so do it deliberately.",
                )
            )

        if state.reclaimable_bytes and state.reclaimable_bytes >= _RECLAIMABLE_WARN_BYTES:
            gigabytes = state.reclaimable_bytes / 1000**3
            out.append(
                self.finding(
                    "containers/disk-reclaimable",
                    FindingState.WARN,
                    f"{gigabytes:.1f} GB of container storage is reclaimable.",
                    evidence=(
                        self.cmd_evidence(
                            ("docker", "system", "df"),
                            f"reclaimable={state.reclaimable_bytes} bytes",
                        ),
                    ),
                    detected=f"{gigabytes:.1f} GB",
                    component="docker",
                    remediation_hint="`docker system prune -a --volumes` reclaims it. This tool "
                    "does not run it: pruning removes data, and which data is yours to decide.",
                )
            )

        # More than one engine installed is not itself wrong -- plenty of people
        # keep Colima beside Docker Desktop on purpose. It is worth naming
        # because it makes `docker context` load-bearing, and a context pointing
        # at a stopped VM produces exactly the same error as no daemon at all.
        if len(state.other_runtimes) >= 2:
            listed = ", ".join(state.other_runtimes)
            out.append(
                self.finding(
                    "containers/multiple-runtimes",
                    FindingState.INFO,
                    f"More than one container engine is installed: {listed}.",
                    evidence=(Evidence(source="system", excerpt=f"resolved on PATH: {listed}"),),
                    detected=listed,
                    component="docker",
                    remediation_hint="`docker context ls` shows which one `docker` currently "
                    "talks to. A context pointing at a stopped VM fails identically to having "
                    "no daemon at all.",
                )
            )

        if state.docker_daemon_ok and state.buildx_version is None:
            out.append(
                self.finding(
                    "containers/buildkit-unavailable",
                    FindingState.INFO,
                    "docker buildx is not available; builds fall back to the legacy builder.",
                    evidence=(self.cmd_evidence(("docker", "buildx", "version"), "not available"),),
                    component="docker",
                    remediation_hint="Multi-platform builds, build secrets and cache mounts all "
                    "need buildx. Install the buildx plugin if a Dockerfile here uses them.",
                )
            )

        return out


def _parse_context(text: str) -> tuple[str | None, str | None]:
    """Name and daemon endpoint from `docker context inspect`.

    The output is a JSON array with one element, and the endpoint is nested at
    `Endpoints.docker.Host`. Both are read defensively: this runs against
    whichever docker is installed, not the one it was written against.
    """
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else None
    if not isinstance(parsed, dict):
        return None, None

    name = parsed.get("Name")
    endpoints = parsed.get("Endpoints")
    host = None
    if isinstance(endpoints, dict):
        docker = endpoints.get("docker")
        if isinstance(docker, dict):
            host = docker.get("Host")
    return (
        name if isinstance(name, str) else None,
        host if isinstance(host, str) else None,
    )


#: Architecture names differ between the host report and the daemon's: Python
#: says `AMD64` on Windows and `arm64` on Apple silicon, docker says `x86_64`
#: and `aarch64`. Comparing them raw reports every Windows machine as emulated.
_ARCH_ALIASES: dict[str, str] = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "i386": "x86",
    "i686": "x86",
    "x86": "x86",
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "armv7l": "arm",
    "arm": "arm",
}


def _normalise_arch(arch: str | None) -> str | None:
    if not arch:
        return None
    return _ARCH_ALIASES.get(arch.strip().lower())
