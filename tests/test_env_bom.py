"""A bill of materials for the environment, and what must never be in it.

Every SBOM tool answers "what did this application vendor in". None answers
"what built it" -- the compiler, the interpreter, the container engine, the
operating system -- and that second list is what turns a reproducible build
into an unreproducible one.

Two properties carry the weight here. The file must contain no paths, because
an executable path names a user's home directory and a BOM is an artefact
people attach to compliance tickets and hand to auditors outside their company.
And it must be deterministic, because an evidence file that differs on every
regeneration cannot be diffed across machines or across time, which is the only
thing it is for.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from devrepro.compliance.envbom import (
    CYCLONEDX_SPEC_VERSION,
    purl_for,
    render_environment_bom,
)
from devrepro.core.models import ContainerState, PlatformInfo, ScanReport, ToolInstallation

TOOLCHAIN_SOURCE = Path(__file__).resolve().parent.parent / "devrepro" / "probes" / "toolchains.py"


def report(
    tools: list[ToolInstallation] | None = None,
    *,
    containers: ContainerState | None = None,
) -> ScanReport:
    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.0.0",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        platform=PlatformInfo(os_name="Linux", os_version="6.8.0", arch="x86_64"),
        findings=(),
        tools=tuple(tools or []),
        requirements=(),
        probe_errors=(),
        containers=containers,
    )


def tool(
    name: str,
    version: str | None = "1.0.0",
    *,
    path: str = "/usr/bin/x",
    source: str = "distro",
    active: bool = True,
) -> ToolInstallation:
    return ToolInstallation(
        name=name, version=version, exe_path=path, install_source=source, is_active=active
    )


def bom(*args: object, **kwargs: object) -> dict:
    return json.loads(render_environment_bom(report(*args, **kwargs)))  # type: ignore[arg-type]


# ------------------------------------------------------------------- privacy


def test_no_executable_path_reaches_the_document() -> None:
    """The property that decides whether this file can be shared at all."""
    private = "/home/anna-surname/.pyenv/versions/3.12.4/bin/python"
    rendered = render_environment_bom(report([tool("python", "3.12.4", path=private)]))
    assert "anna-surname" not in rendered
    assert ".pyenv/versions" not in rendered
    assert "/home/" not in rendered


def test_the_provenance_is_kept_even_though_the_path_is_not() -> None:
    """Where a tool came from is the reproducibility-relevant half."""
    components = bom([tool("python", "3.12.4", source="pyenv")])["components"]
    python = next(c for c in components if c["name"] == "python")
    assert "version manager" in python["description"]
    assert any(p["name"] == "devrepro:install-source" for p in python["properties"])


def test_the_host_is_not_named() -> None:
    """A hostname is frequently a person's name or an unreleased codename."""
    subject = bom()["metadata"]["component"]
    assert subject["name"] == "host"


def test_the_document_says_why_paths_are_absent() -> None:
    """An auditor asking "where is the path" should find the answer in the file."""
    note = json.dumps(bom()["metadata"]["properties"])
    assert "usernames" in note


# ------------------------------------------------------------- determinism


def test_the_same_report_renders_byte_identically() -> None:
    """Including the serial number.

    A random UUID is more conventional and would make every regeneration a
    diff, which defeats an artefact whose purpose is being compared.
    """
    scan = report([tool("python", "3.12.4")])
    assert render_environment_bom(scan) == render_environment_bom(scan)


def test_a_component_ref_follows_its_identity_not_its_position() -> None:
    """So a diff of two BOMs shows what changed, not everything shifting."""
    one = bom([tool("git", "2.45.0"), tool("python", "3.12.4")])
    two = bom([tool("python", "3.12.4"), tool("git", "2.45.0")])
    refs = {c["name"]: c["bom-ref"] for c in one["components"]}
    assert refs == {c["name"]: c["bom-ref"] for c in two["components"]}


def test_components_are_ordered_by_name() -> None:
    names = [c["name"] for c in bom([tool("zsh"), tool("git"), tool("node")])["components"]]
    assert names == sorted(names)


# ---------------------------------------------------------------- structure


def test_it_is_a_cyclonedx_document() -> None:
    document = bom()
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == CYCLONEDX_SPEC_VERSION
    assert document["serialNumber"].startswith("urn:uuid:")
    assert document["version"] == 1


def test_the_platform_is_the_subject_and_not_repeated_as_a_component() -> None:
    document = bom([tool("git")])
    assert document["metadata"]["component"]["type"] == "platform"
    assert [c["name"] for c in document["components"]] == ["git"]


def test_the_generating_tool_identifies_itself() -> None:
    tools = bom()["metadata"]["tools"]["components"]
    assert tools[0]["name"] == "devrepro-doctor"


def test_the_container_engine_is_a_component_when_one_answered() -> None:
    """A build in a container is reproduced by the engine as much as the compiler."""
    state = ContainerState(
        docker_daemon_ok=True,
        backend="colima",
        server_version="26.1.3",
        storage_driver="overlay2",
        cgroup_version="2",
    )
    components = bom(containers=state)["components"]
    engine = next(c for c in components if c["name"] == "colima")
    assert engine["version"] == "26.1.3"
    assert any(p["value"] == "overlay2" for p in engine["properties"])


def test_no_engine_component_when_the_daemon_did_not_answer() -> None:
    state = ContainerState(docker_daemon_ok=False, backend="docker-desktop")
    assert bom(containers=state)["components"] == []


# ------------------------------------------------------------------- content


def test_a_tool_with_no_version_is_omitted() -> None:
    """A component without a version identifies nothing checkable."""
    assert bom([tool("mystery", None)])["components"] == []


def test_one_component_per_tool_even_with_several_installations() -> None:
    """Three Pythons on PATH is a fact about PATH, not about the build.

    The count is kept as a property, because "there were three and this is the
    one that won" is what a reproducibility question turns on.
    """
    components = bom(
        [
            tool("python", "3.12.4", active=True),
            tool("python", "3.11.9", active=False),
            tool("python", "3.10.0", active=False),
        ]
    )["components"]

    assert len(components) == 1
    assert components[0]["version"] == "3.12.4"
    assert any(p["value"] == "3" for p in components[0]["properties"])


def test_the_active_installation_wins() -> None:
    components = bom([tool("node", "18.0.0", active=False), tool("node", "22.4.0", active=True)])[
        "components"
    ]
    assert components[0]["version"] == "22.4.0"


@pytest.mark.parametrize("name", ["python", "node", "docker", "cargo"])
def test_well_known_tools_get_a_generic_purl(name: str) -> None:
    assert purl_for(name, "1.2.3") == f"pkg:generic/{name}@1.2.3"


def test_an_unknown_tool_gets_no_purl() -> None:
    """A PURL that resolves to nothing invites a scanner to report an absence."""
    assert purl_for("some-internal-tool", "1.0") is None


def test_a_versionless_tool_gets_no_purl() -> None:
    assert purl_for("python", None) is None


# ----------------------------------------------------- the table's own truth


def test_every_provenance_key_is_one_the_probe_emits() -> None:
    """The bug this test was written for.

    The first version of the provenance table invented its own vocabulary --
    `system-package-manager`, `version-manager` -- none of which
    `_install_source` produces. So every component in the BOM described itself
    as "provenance could not be determined" while the scan report beside it
    knew perfectly well.

    A lookup whose keys come from another module has to be checked against that
    module, or it silently degrades to its default.
    """
    import re

    from devrepro.compliance.envbom import _PROVENANCE

    source = TOOLCHAIN_SOURCE.read_text(encoding="utf-8")
    block = source.split("markers = [", 1)[1].split("]", 1)[0]
    emitted = set(re.findall(r'"([a-z0-9-]+)"\s*\)', block))
    emitted.add("unknown")  # the fallback, returned rather than listed

    documented = set(_PROVENANCE)
    assert emitted <= documented, (
        f"the probe emits {sorted(emitted - documented)}, which the BOM would "
        "describe as unknown provenance"
    )


def test_the_default_only_applies_to_genuinely_unknown_sources() -> None:
    components = bom([tool("thing", "1.0", source="distro")])["components"]
    assert "could not be determined" not in components[0]["description"]
