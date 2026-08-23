"""Port declarations, conflict detection and local service health probes.

Capabilities:
- parse declared ports from docker-compose files, devcontainer.json and
  .devrepro.toml;
- detect port conflicts by attempting a local bind (no process killing,
  owning-process evidence is reported as a redacted PID only);
- TCP health probes for project-declared services (PostgreSQL, MySQL,
  Redis, RabbitMQ, MinIO, ...) — protocol-level checks stay opt-in.
"""

from __future__ import annotations

import json
import re
import socket
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "PortDeclaration",
    "PortStatus",
    "ServiceProbeResult",
    "check_port_conflicts",
    "collect_port_declarations",
    "probe_services",
]

# well-known development services: name -> default port
KNOWN_SERVICES: dict[str, int] = {
    "postgres": 5432,
    "mysql": 3306,
    "redis": 6379,
    "rabbitmq": 5672,
    "minio": 9000,
    "mongo": 27017,
    "elasticsearch": 9200,
    "mailhog": 1025,
}


@dataclass(frozen=True)
class PortDeclaration:
    port: int
    source_file: str
    service: str | None = None  # e.g. postgres when inferable


@dataclass(frozen=True)
class PortStatus:
    port: int
    free: bool
    service: str | None


@dataclass(frozen=True)
class ServiceProbeResult:
    service: str
    host: str
    port: int
    reachable: bool
    detail: str


def _compose_ports(path: Path, rel: str) -> list[PortDeclaration]:
    out: list[PortDeclaration] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    current_service: str | None = None
    for line in text.splitlines():
        m_svc = re.match(r"^ {2}([\w-]+):\s*$", line)
        if m_svc:
            current_service = m_svc.group(1)
        m_ports = re.match(r'^\s*-\s*"?(\d+)(?::\d+)?"?\s*$', line)
        if m_ports and current_service:
            out.append(PortDeclaration(int(m_ports.group(1)), rel, current_service))
    return out


def _devcontainer_ports(path: Path, rel: str) -> list[PortDeclaration]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("forwardPorts") or data.get("appPort") or []
    if isinstance(raw, (int, str)):
        raw = [raw]
    out: list[PortDeclaration] = []
    for item in raw:
        try:
            port = int(str(item).split(":")[0])
        except ValueError:
            continue
        if 0 < port < 65536:
            out.append(PortDeclaration(port, rel))
    return out


def _policy_ports(root: Path) -> list[PortDeclaration]:
    p = root / ".devrepro.toml"
    if not p.is_file():
        return []
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    ports = data.get("required_ports") or []
    return [
        PortDeclaration(int(v), ".devrepro.toml")
        for v in ports
        if isinstance(v, int) and 0 < v < 65536
    ]


def collect_port_declarations(root: Path | str) -> tuple[PortDeclaration, ...]:
    """Collect every port the project declares across config files."""
    root = Path(root)
    decls: list[PortDeclaration] = []
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        p = root / name
        if p.is_file():
            decls.extend(_compose_ports(p, name))
    dc = root / ".devcontainer" / "devcontainer.json"
    if dc.is_file():
        decls.extend(_devcontainer_ports(dc, ".devcontainer/devcontainer.json"))
    decls.extend(_policy_ports(root))
    seen: set[tuple[int, str]] = set()
    unique: list[PortDeclaration] = []
    for d in decls:
        key = (d.port, d.source_file)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return tuple(unique)


def check_port_conflicts(decls: tuple[PortDeclaration, ...]) -> tuple[PortStatus, ...]:
    """For each declared port, test whether it can be bound locally."""
    statuses: list[PortStatus] = []
    for d in decls:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.bind(("127.0.0.1", d.port))
            free = True
        except OSError:
            free = False
        finally:
            s.close()
        statuses.append(PortStatus(port=d.port, free=free, service=d.service))
    return tuple(statuses)


def probe_services(
    services: dict[str, tuple[str, int]] | None = None,
    timeout: float = 1.0,
) -> tuple[ServiceProbeResult, ...]:
    """TCP-reachability probes for project-declared local services.

    ``services`` maps service name -> (host, port); defaults to the
    well-known development services on localhost.
    """
    targets = services or {name: ("127.0.0.1", port) for name, port in KNOWN_SERVICES.items()}
    results: list[ServiceProbeResult] = []
    for name in sorted(targets):
        host, port = targets[name]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            results.append(ServiceProbeResult(name, host, port, True, "TCP connect succeeded"))
        except OSError as exc:
            reason = type(exc).__name__
            results.append(ServiceProbeResult(name, host, port, False, f"unreachable ({reason})"))
        finally:
            s.close()
    return tuple(results)


def _compose_images(root: Path) -> dict[str, str]:
    """Map compose service name -> image reference (e.g. db -> postgres:16)."""
    out: dict[str, str] = {}
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        p = root / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        current_service: str | None = None
        for line in text.splitlines():
            m_svc = re.match(r"^ {2}([\w-]+):\s*$", line)
            if m_svc:
                current_service = m_svc.group(1)
            m_img = re.match(r'^\s+image:\s*"?([\w./:-]+)"?', line)
            if m_img and current_service:
                out[current_service] = m_img.group(1)
    return out


def infer_required_services(root: Path | str) -> dict[str, tuple[str, int]]:
    """Infer which known services this project expects, from compose/policy."""
    root = Path(root)
    decls = collect_port_declarations(root)
    images = _compose_images(root)
    inferred: dict[str, tuple[str, int]] = {}

    def known_from(name: str) -> str | None:
        base = name.lower().split(":")[0].split("/")[-1]
        return base if base in KNOWN_SERVICES else None

    # first pass: match declared ports to services via image references
    for d in decls:
        candidates = []
        if d.service:
            candidates.append(d.service)
            img = images.get(d.service)
            if img:
                candidates.append(img)
        for cand in candidates:
            svc = known_from(cand)
            if svc and svc not in inferred:
                inferred[svc] = ("127.0.0.1", d.port)
                break
    # second pass: well-known default ports without any declaration evidence
    for d in decls:
        if d.port in KNOWN_SERVICES.values() and not any(p == d.port for _, p in inferred.values()):
            for svc, port in KNOWN_SERVICES.items():
                if port == d.port and svc not in inferred:
                    inferred[svc] = ("127.0.0.1", d.port)
                    break
    return inferred
