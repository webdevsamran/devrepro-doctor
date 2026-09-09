"""Shared pytest fixtures. Tests never depend on the real machine."""

from __future__ import annotations

from pathlib import Path

import pytest
from devrepro.core.models import PlatformInfo
from devrepro.core.runner import CommandResult, RecordingRunner
from devrepro.probes.base import ProbeContext

FIXTURES = Path(__file__).parent / "fixtures"
RECORDINGS = FIXTURES / "recordings"

#: PATH separator for each recorded machine, so a recording can drive a probe
#: whose ``ctx.platform`` differs from the host running the tests.
_PATH_SEPARATORS = {"windows": ";"}


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture()
def recordings_dir() -> Path:
    return RECORDINGS


def recorded_path(machine: str) -> str:
    """Load ``recordings/<machine>/path.txt`` as a single PATH string.

    The file stores one entry per line so it stays reviewable in a diff; probes
    want the joined form. The separator follows the *recorded* machine, not the
    host, which is what lets a Windows recording drive a probe on a Linux CI leg.
    """
    lines = (RECORDINGS / machine / "path.txt").read_text(encoding="utf-8").splitlines()
    return _PATH_SEPARATORS.get(machine, ":").join(line for line in lines if line.strip())


def recorded_docker_failures() -> dict[str, dict[str, object]]:
    """Load the recorded ``docker info`` / ``docker version`` failure shapes."""
    import json

    raw = (RECORDINGS / "docker" / "failures.json").read_text(encoding="utf-8")
    return dict(json.loads(raw))


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
