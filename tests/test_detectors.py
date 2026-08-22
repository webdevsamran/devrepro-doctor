"""Manifest/lockfile requirement detection against fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from devrepro.project.detectors import detect_project_kind, detect_requirements

FIX = Path(__file__).parent / "fixtures" / "manifests"


def _reqs(name: str):
    return detect_requirements(FIX / name)


def test_python_project() -> None:
    reqs = _reqs("python-project")
    names = {(r.ecosystem, r.name) for r in reqs}
    assert ("python", "python") in names
    assert any(r.name == "requests" for r in reqs)
    assert any(r.name == "flask" for r in reqs)
    py = next(r for r in reqs if r.name == "python")
    assert py.spec == ">=3.11,<3.14"


def test_node_project() -> None:
    reqs = _reqs("node-project")
    node = next(r for r in reqs if r.name == "node")
    assert node.spec == ">=20 <23"
    assert any(r.source_file.endswith(".nvmrc") for r in reqs)


def test_rust_project() -> None:
    reqs = _reqs("rust-project")
    rust = next(r for r in reqs if r.name == "rustc")
    assert rust.spec == "1.75"


def test_go_project() -> None:
    reqs = _reqs("go-project")
    go = next(r for r in reqs if r.name == "go")
    assert go.spec.replace(">=", "").startswith("1.22")


def test_dotnet_project() -> None:
    reqs = _reqs("dotnet-project")
    assert any(r.name == "target-framework" and "8.0" in (r.spec or "") for r in reqs)


def test_kinds() -> None:
    kinds = detect_project_kind(FIX / "node-project")
    assert "node" in kinds


def test_empty_dir(tmp_path: Path) -> None:
    assert detect_requirements(tmp_path) == []


@pytest.mark.parametrize("name", ["python-project", "node-project"])
def test_never_invents_versions(name: str) -> None:
    for r in _reqs(name):
        if r.kind.value == "runtime":
            assert r.spec is not None