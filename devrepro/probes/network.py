"""Network/TLS doctor probe.

Checks DNS resolution, proxy settings, clock skew, TLS trust against
common development endpoints, and registry reachability — classifying
failures as network / tls / auth-required / rate-limit / unavailable.

Never disables certificate validation, ever.
"""

from __future__ import annotations

import contextlib
import re
import socket
import ssl
from datetime import UTC, datetime

from devrepro.core.models import Evidence, FindingState
from devrepro.probes.base import Probe, ProbeResult

__all__ = ["NetworkTlsProbe"]

_ENDPOINTS: tuple[tuple[str, int], ...] = (
    ("github.com", 443),
    ("registry.npmjs.org", 443),
    ("pypi.org", 443),
)

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)

_RATE_LIMIT_RE = re.compile(r"(429|rate limit)", re.IGNORECASE)
_AUTH_RE = re.compile(r"(401|403|unauthorized|forbidden|authentication required)", re.IGNORECASE)


def classify_http_failure(status_or_error: str) -> str:
    if _RATE_LIMIT_RE.search(status_or_error):
        return "rate-limit"
    if _AUTH_RE.search(status_or_error):
        return "authentication-required"
    if any(k in status_or_error.lower() for k in ("certificate", "ssl", "tls", "verify")):
        return "tls-failure"
    if any(k in status_or_error.lower() for k in ("timeout", "unreachable", "refused", "dns")):
        return "network-failure"
    return "service-unavailable"


class NetworkTlsProbe(Probe):
    """Proxy configuration always; anything that opens a socket only on request.

    The split is the point. Reading `HTTPS_PROXY` out of the environment is a
    local fact and belongs in every scan. Connecting to github.com to see
    whether it answers is a network side effect -- it tells that host, and any
    proxy in the path, that this machine ran this tool -- and this project's
    rule is that side effects are asked for by name.

    `ctx.extra["allow_network"]` carries the answer, set from the same
    `--allow-network` flag `devrepro network` already had. It defaults to
    false, so `doctor`, `scan`, `preflight`, `guard` and `snapshot` make no
    connections at all.
    """

    id = "network/tls"
    version = "2"

    def run(self) -> ProbeResult:
        findings = []
        data: dict[str, object] = {}

        # -- proxy configuration (names + host only, never credentials) ----
        proxies = {k: self.ctx.env[k] for k in _PROXY_ENV_KEYS if self.ctx.env.get(k)}
        redacted_proxies = {k: re.sub(r"//[^@/]+@", "//***@", v) for k, v in proxies.items()}
        data["proxies"] = redacted_proxies

        # Everything below this line opens a socket, and this project's rule is
        # that a side effect is asked for by name. Reading proxy environment
        # variables is local; reaching github.com to see whether it answers is
        # not, and it tells that host -- and every proxy in between -- that this
        # machine ran this tool.
        allow_network = bool(self.ctx.extra.get("allow_network", False))
        data["network_checks_opt_in"] = allow_network
        if not allow_network:
            findings.append(
                self.finding(
                    "network/checks-skipped",
                    FindingState.INFO,
                    "Endpoint reachability and TLS were not checked: they open "
                    "connections, and this scan did not ask for them.",
                    evidence=(
                        Evidence(
                            source="system",
                            excerpt="allow_network=False",
                        ),
                    ),
                    component="network",
                    remediation_hint=(
                        "Run `devrepro network --allow-network` to check DNS, TLS and "
                        "registry reachability. Proxy configuration above was read from "
                        "environment variables and needed no connection."
                    ),
                )
            )
            return ProbeResult(self.id, findings=tuple(findings), data=data)

        # -- clock skew -------------------------------------------------------
        skew = self._clock_skew_seconds()
        data["clock_skew_seconds"] = skew
        if skew is not None and abs(skew) > 300:
            findings.append(
                self.finding(
                    "network/clock-skew",
                    FindingState.ERROR,
                    f"System clock differs from network time by ~{int(abs(skew))}s; "
                    "TLS validation will fail unpredictably.",
                    evidence=(Evidence(source="network", excerpt=f"skew={skew:.0f}s"),),
                    detected=f"{skew:.0f}s",
                    component="network",
                    remediation_hint="Enable automatic time sync (NTP). Never work around this "
                    "by disabling certificate verification.",
                )
            )

        # -- endpoint reachability + TLS ---------------------------------------
        failures: list[str] = []
        for host, port in _ENDPOINTS:
            ok, detail = self._check_endpoint(host, port)
            data[f"endpoint/{host}"] = {"ok": ok, "detail": detail}
            if not ok:
                failures.append(f"{host}: {classify_http_failure(detail)} ({detail})")

        if failures:
            findings.append(
                self.finding(
                    "network/endpoint-unreachable",
                    FindingState.WARN,
                    f"{len(failures)} development endpoint(s) unreachable or failing TLS.",
                    evidence=(Evidence(source="network", excerpt="; ".join(failures)[:1000]),),
                    component="network",
                    remediation_hint="Check proxy settings, corporate CA trust store, and DNS. "
                    "DevRepro will never suggest disabling certificate validation.",
                )
            )
        else:
            findings.append(
                self.finding(
                    "network/endpoints-ok",
                    FindingState.PASS,
                    "All checked development endpoints reachable with valid TLS.",
                    evidence=(
                        Evidence(
                            source="network", excerpt="github.com, registry.npmjs.org, pypi.org OK"
                        ),
                    ),
                    component="network",
                )
            )

        return ProbeResult(self.id, findings=tuple(findings), data=data)

    @staticmethod
    def _check_endpoint(host: str, port: int) -> tuple[bool, str]:
        try:
            sock = socket.create_connection((host, port), timeout=5)
        except OSError as exc:
            return False, f"connect failed: {exc}"
        try:
            ctx = ssl.create_default_context()  # full verification, always
            # See devrepro/network/diagnostics.py for why the floor is stated
            # rather than inherited from the OpenSSL build.
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                not_after = cert.get("notAfter") if isinstance(cert, dict) else None
                return True, f"tls-ok until {not_after}"
        except ssl.SSLError as exc:
            return False, f"tls-failure: {exc}"
        except OSError as exc:
            return False, f"tls-handshake failed: {exc}"
        finally:
            with contextlib.suppress(OSError):
                sock.close()

    @staticmethod
    def _clock_skew_seconds() -> float | None:
        """Compare local wall clock to an HTTPS response Date header."""
        try:
            sock = socket.create_connection(("github.com", 443), timeout=5)
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2  # see _check_endpoint
            crlf = chr(13) + chr(10)
            request = (
                "HEAD / HTTP/1.1"
                + crlf
                + "Host: github.com"
                + crlf
                + "Connection: close"
                + crlf
                + crlf
            ).encode("latin-1")
            with ctx.wrap_socket(sock, server_hostname="github.com") as tls:
                tls.sendall(request)
                raw = b""
                terminator = (crlf * 2).encode("latin-1")
                while terminator not in raw and len(raw) < 8192:
                    chunk = tls.recv(1024)
                    if not chunk:
                        break
                    raw += chunk
            head = raw.decode("latin-1", errors="replace")
            date_line = next(
                (ln for ln in head.splitlines() if ln.lower().startswith("date:")),
                None,
            )
            if not date_line:
                return None
            from email.utils import parsedate_to_datetime

            remote = parsedate_to_datetime(date_line.split(":", 1)[1].strip())
            if remote.tzinfo is None:
                remote = remote.replace(tzinfo=UTC)
            return (datetime.now(UTC) - remote).total_seconds()
        except Exception:
            return None
        finally:
            with contextlib.suppress(Exception):
                sock.close()
