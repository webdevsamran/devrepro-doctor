"""Ports/services probe: identify common dev ports in use and the owning
process PID — without exposing unrelated command lines or secrets.
"""

from __future__ import annotations

import re
import socket
import subprocess

from devrepro.core.models import Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["PortsServicesProbe"]

_COMMON_DEV_PORTS: tuple[int, ...] = (
    3000,
    3001,
    4200,
    5000,
    5173,
    5432,
    6379,
    8000,
    8080,
    8081,
    9000,
    27017,
)


class PortsServicesProbe(Probe):
    id = "ports/services"
    version = "1"

    def run(self) -> ProbeResult:
        findings = []
        busy: dict[int, int | None] = {}
        for port in _COMMON_DEV_PORTS:
            owner = self._port_owner(port)
            if owner is not None:
                busy[port] = owner

        for port, pid in sorted(busy.items()):
            findings.append(
                self.finding(
                    "ports/port-in-use",
                    FindingState.INFO,
                    f"Port {port} is in use by PID {pid}.",
                    evidence=(
                        Evidence(source="system", excerpt=f"port {port} listening, pid={pid}"),
                    ),
                    detected=str(port),
                    component="ports",
                )
            )

        return ProbeResult(
            self.id,
            findings=tuple(findings),
            data={"busy_ports": {str(k): v for k, v in busy.items()}},
        )

    def _port_owner(self, port: int) -> int | None:
        """Return owning PID if the port is listening locally, else None."""
        if self._is_open(port):
            return self._owner_pid(port)
        return None

    @staticmethod
    def _is_open(port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            result = sock.connect_ex(("127.0.0.1", port))
            return result == 0
        finally:
            sock.close()

    @staticmethod
    def _owner_pid(port: int) -> int | None:
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10, check=False
            ).stdout
            pattern = re.compile(rf":{port}\s+.*LISTENING\s+(\d+)", re.IGNORECASE)
            m = pattern.search(out)
            return int(m.group(1)) if m else None
        except Exception:
            return None
