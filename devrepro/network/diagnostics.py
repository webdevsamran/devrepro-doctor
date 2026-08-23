"""Network diagnostics: proxy chain, TLS trust, clock sanity, registry reachability.

Design rules:
- ALL network-touching checks are opt-in (``allow_network=True``);
- proxy URLs are collected with credentials stripped;
- TLS checks never disable verification — they classify failures
  (expired / unknown CA / hostname mismatch / clock skew);
- no host is contacted except user-requested or well-known package
  registries.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

__all__ = [
    "ClockCheck",
    "ProxyReport",
    "RegistryCheck",
    "TlsCheck",
    "check_clock",
    "check_registry",
    "check_tls",
    "collect_proxy_settings",
]

WELL_KNOWN_REGISTRIES: dict[str, str] = {
    "npm": "https://registry.npmjs.org/",
    "pypi": "https://pypi.org/simple/",
    "nuget": "https://api.nuget.org/v3/index.json",
    "maven": "https://repo.maven.apache.org/maven2/",
    "crates": "https://crates.io/api/v1/crates",
    "packagist": "https://repo.packagist.org/packages.json",
}

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)

_CRED_IN_URL = re.compile(r"(?<=//)[^@/\s]+(?=@)")


def _strip_credentials(url: str) -> str:
    return _CRED_IN_URL.sub("***", url)


@dataclass(frozen=True)
class ProxyReport:
    env_proxies: dict[str, str]  # var name -> credential-free URL
    git_proxy: str | None
    npm_proxy: bool  # presence only, value not read from .npmrc secrets
    pip_proxy: bool


def collect_proxy_settings() -> ProxyReport:
    """Collect proxy configuration with all credentials redacted."""
    env: dict[str, str] = {}
    for key in _PROXY_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = _strip_credentials(val)
    # git http.proxy (config value may embed creds; strip them)
    from devrepro.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    res = runner.run(("git", "config", "--get", "http.proxy"), timeout=5.0)
    git_proxy = None
    if res.returncode == 0 and (res.stdout or "").strip():
        git_proxy = _strip_credentials(res.stdout.strip())

    # npm/pip: report PRESENCE of a proxy setting without dumping config files
    def _has_config(tool: tuple[str, ...], needle: str) -> bool:
        r = runner.run((*tool, "config", "--get", needle), timeout=8.0)
        return r.returncode == 0 and bool((r.stdout or "").strip())

    try:
        npm_proxy = _has_config(("npm",), "proxy") or _has_config(("npm",), "https-proxy")
    except Exception:
        npm_proxy = False
    try:
        pip_proxy = _has_config(("pip",), "proxy")
    except Exception:
        pip_proxy = False
    return ProxyReport(
        env_proxies=env,
        git_proxy=git_proxy,
        npm_proxy=npm_proxy,
        pip_proxy=pip_proxy,
    )


@dataclass(frozen=True)
class TlsCheck:
    host: str
    ok: bool
    classification: str  # ok | expired | unknown-ca | hostname-mismatch | clock-skew | error
    detail: str


def check_tls(host: str, port: int = 443, timeout: float = 5.0) -> TlsCheck:
    """Classify TLS trust for a host WITHOUT disabling verification."""
    ctx = ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as sock,
            ctx.wrap_socket(sock, server_hostname=host) as tls,
        ):
            cert = tls.getpeercert()
            not_after = cert.get("notAfter") if cert else None
            expires = (
                datetime.strptime(str(not_after), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
                if not_after
                else None
            )
            days_left = (expires - datetime.now(UTC)).days if expires else None
            return TlsCheck(
                host,
                True,
                "ok",
                f"certificate valid; {days_left} day(s) remaining"
                if days_left is not None
                else "certificate valid",
            )
    except ssl.SSLCertVerificationError as exc:
        reason = getattr(exc, "verify_message", "") or ""
        code = getattr(exc, "verify_code", 0) or 0
        if "expired" in reason.lower() or code == 10:
            cls = "expired"
        elif code == 20:  # unable to get local issuer certificate
            cls = "unknown-ca"
        elif (
            code in (50,) or "hostname mismatch" in reason.lower()
        ):  # pragma: no cover - codes vary
            cls = "hostname-mismatch"
        elif code == 9:  # certificate is not yet valid -> often clock skew
            cls = "clock-skew"
        else:
            cls = "error"
        return TlsCheck(host, False, cls, f"{type(exc).__name__}: {reason or exc}")
    except OSError as exc:
        return TlsCheck(host, False, "error", f"{type(exc).__name__}: {exc}")


@dataclass(frozen=True)
class RegistryCheck:
    name: str
    url: str
    reachable: bool
    status_or_error: str


def check_registry(name: str, url: str | None = None, timeout: float = 5.0) -> RegistryCheck:
    """HEAD/GET reachability probe against a package registry."""
    target = url or WELL_KNOWN_REGISTRIES.get(name)
    if target is None:
        return RegistryCheck(name, url or "", False, "unknown registry")
    parsed = urlparse(target)
    if parsed.scheme != "https":
        return RegistryCheck(name, target, False, "refusing non-HTTPS registry check")
    try:
        import urllib.request

        req = urllib.request.Request(  # noqa: S310 - https enforced above
            target, method="GET", headers={"User-Agent": "devrepro-doctor"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https enforced above
            return RegistryCheck(name, target, True, f"HTTP {resp.status}")
    except Exception as exc:
        return RegistryCheck(name, target, False, f"{type(exc).__name__}: {exc}")


@dataclass(frozen=True)
class ClockCheck:
    utc_now: str
    skew_seconds: float | None  # vs HTTP Date header when network allowed
    plausible: bool
    detail: str


def check_clock(allow_network: bool = False) -> ClockCheck:
    """System-clock sanity. With network, compare against an HTTPS Date header."""
    now = datetime.now(UTC)
    iso = now.isoformat(timespec="seconds")
    if not allow_network:
        # offline plausibility: year within a sane range
        plausible = 2023 <= now.year <= 2035
        return ClockCheck(iso, None, plausible, "offline sanity check only")
    try:
        import urllib.request

        req = urllib.request.Request(  # noqa: S310 - fixed https URL
            WELL_KNOWN_REGISTRIES["pypi"], method="GET", headers={"User-Agent": "devrepro-doctor"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310 - fixed https URL
            date_hdr = resp.headers.get("Date")
        if not date_hdr:
            return ClockCheck(iso, None, True, "no Date header returned; skipped skew estimate")
        remote = datetime.strptime(date_hdr, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=UTC)
        skew = (now - remote).total_seconds()
        plausible = abs(skew) < 300
        return ClockCheck(
            iso,
            skew,
            plausible,
            f"clock skew vs authoritative server: {skew:+.0f}s "
            + ("OK" if plausible else "TOO LARGE — certificates/tokens will fail"),
        )
    except Exception as exc:
        return ClockCheck(iso, None, True, f"skew check unavailable ({type(exc).__name__})")
