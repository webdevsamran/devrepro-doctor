"""Wave-5 capability tests: plugin API v2 and engine self-test."""

from __future__ import annotations

import pytest
from devrepro.core.selftest import run_selftest
from devrepro.plugins.v2 import (
    PluginManifest,
    conformance_report,
    run_isolated,
)

# ---------- plugin API v2 ----------


def test_manifest_rejects_unknown_capability() -> None:
    with pytest.raises(ValueError, match="unknown capabilities"):
        PluginManifest(name="x", version="1.0.0", capabilities=("teleport",))


def test_manifest_warning_capabilities() -> None:
    quiet = PluginManifest(name="q", version="1.0.0")
    loud = PluginManifest(name="l", version="1.0.0", capabilities=("network",))
    assert not quiet.needs_warning
    assert loud.needs_warning


def test_run_isolated_captures_success() -> None:
    m = PluginManifest(name="ok-plugin", version="1.0.0")
    res = run_isolated(m, lambda: 42)
    assert res.ok
    assert res.value == 42


def test_run_isolated_never_propagates_crash() -> None:
    m = PluginManifest(name="bad-plugin", version="1.0.0")

    def boom() -> None:
        raise RuntimeError("plugin exploded")

    res = run_isolated(m, boom)
    assert not res.ok
    assert "RuntimeError" in (res.error or "")
    assert res.value is None


class _GoodPlugin:
    """Reference v2-conformant plugin."""

    manifest = PluginManifest(
        name="reference",
        version="1.0.0",
        capabilities=("subprocess",),
        description="reference implementation",
    )

    def probe(self) -> dict[str, str]:
        return {"status": "ok"}


def test_conformance_kit_passes_reference_plugin() -> None:
    report = conformance_report(_GoodPlugin())
    assert report["conformant"], report["failed_checks"]
    assert report["plugin"] == "reference"


def test_conformance_kit_fails_undocumented_plugin() -> None:
    class _Bad:
        pass

    report = conformance_report(_Bad())
    assert not report["conformant"]
    assert "entrypoint" in report["failed_checks"]
    assert "documented" in report["failed_checks"]


# ---------- self-test ----------


def test_selftest_all_checks_pass() -> None:
    report = run_selftest()
    names = [c.name for c in report.checks]
    assert {
        "probe-determinism",
        "redaction",
        "temp-directories",
        "subprocess-capture",
        "readonly-probes",
    } <= set(names)
    failed = [c for c in report.checks if not c.passed]
    assert not failed, [(c.name, c.detail) for c in failed]
    assert report.ok
