"""Shared pytest fixtures. Tests never depend on the real machine."""

from __future__ import annotations

from pathlib import Path

import pytest
from devrepro.core.models import PlatformInfo
from devrepro.core.runner import CommandResult, RecordingRunner
from devrepro.probes.base import ProbeContext

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES


def make_ctx(
    responses: dict[str, CommandResult] | None = None,
    *,
    platform: str = "linux",
    env: dict[str, str] | None = None,
    project_dir: Path | None = None,
) -> ProbeContext:
    """Build a ProbeContext backed by a RecordingRunner."""
    runner = RecordingRunner(responses or {})
    info = PlatformInfo(os_name=platform.title(), os_version="1", arch="x86_64")
    return ProbeContext(
        runner=runner,
        platform=platform,
        platform_info=info,
        project_dir=project_dir,
        env=env if env is not None else {"PATH": "/usr/bin:/bin"},
    )


@pytest.fixture()
def ctx_factory():
    return make_ctx
