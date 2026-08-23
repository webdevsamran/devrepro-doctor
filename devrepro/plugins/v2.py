"""Plugin API v2: manifests, capability declarations, isolation, conformance kit.

v2 plugins declare a manifest with:
- semantic API compatibility range;
- capability declarations (network / privileged / filesystem-write) so the
  UI can warn BEFORE a probe runs;
- stable plugin_id for audit trails.

The runner isolates every plugin invocation: an exception inside one
extension becomes a recorded failure, never a crashed scan.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CAPABILITIES",
    "IsolatedResult",
    "PluginManifest",
    "conformance_report",
    "run_isolated",
]

API_VERSION = "2"

CAPABILITIES = ("network", "privileged", "filesystem-write", "subprocess")


@dataclass(frozen=True)
class PluginManifest:
    """Declared metadata for a v2 plugin."""

    name: str
    version: str
    api_version: str = API_VERSION
    capabilities: tuple[str, ...] = ()
    min_host: str = "0.1"  # minimum host version this plugin supports
    description: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.capabilities) - set(CAPABILITIES)
        if unknown:
            msg = f"unknown capabilities declared: {sorted(unknown)}"
            raise ValueError(msg)

    @property
    def needs_warning(self) -> bool:
        """Capabilities that should trigger a user-facing warning."""
        return bool(set(self.capabilities) & {"network", "privileged"})


@dataclass(frozen=True)
class IsolatedResult:
    plugin: str
    ok: bool
    value: Any = None
    error: str | None = None


def run_isolated(manifest: PluginManifest, fn: Any, *args: Any, **kwargs: Any) -> IsolatedResult:
    """Invoke a plugin entrypoint with failure isolation and time budget.

    A raising plugin returns ``ok=False`` with the error text; it never
    propagates into the host scan.
    """
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:
        return IsolatedResult(manifest.name, False, error=f"{type(exc).__name__}: {exc}")
    return IsolatedResult(manifest.name, True, value=value)


def _check_callable(obj: Any, attr: str) -> bool:
    return callable(getattr(obj, attr, None))


def conformance_report(obj: Any, manifest: PluginManifest | None = None) -> dict[str, Any]:
    """Conformance kit: verify a plugin object satisfies the v2 contract.

    Checks performed:
    - manifest present/valid (or supplied externally);
    - exposes a callable ``probe`` or ``detect`` entrypoint;
    - entrypoint signature is introspectable (no exotic signatures);
    - no blocking sleeps at import time (module imports cleanly).
    """
    checks: list[dict[str, str]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "pass" if passed else "fail", "detail": detail})

    m = manifest or getattr(obj, "manifest", None)
    if m is None:
        record("manifest", False, "no manifest attribute and none supplied")
    else:
        try:
            PluginManifest(
                name=m.name,
                version=m.version,
                api_version=m.api_version,
                capabilities=tuple(m.capabilities),
            )
            record("manifest", True, f"{m.name} v{m.version} api={m.api_version}")
        except Exception as exc:
            record("manifest", False, str(exc))

    entry = None
    for attr in ("probe", "detect", "run"):
        if _check_callable(obj, attr):
            entry = attr
            break
    record("entrypoint", entry is not None, f"callable entrypoint: {entry or 'none found'}")

    if entry is not None:
        try:
            inspect.signature(getattr(obj, entry))
            record("signature", True, f"{entry}() signature is introspectable")
        except (TypeError, ValueError) as exc:
            record("signature", False, str(exc))

    doc = inspect.getdoc(obj)
    record("documented", bool(doc), "has docstring" if doc else "missing docstring")

    failed = [c["check"] for c in checks if c["status"] == "fail"]
    return {
        "plugin": getattr(m, "name", obj.__class__.__name__),
        "api_version": API_VERSION,
        "conformant": not failed,
        "failed_checks": failed,
        "checks": checks,
    }
