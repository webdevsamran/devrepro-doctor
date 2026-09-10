"""A CycloneDX bill of materials for the *environment*, not the dependencies.

Every SBOM tool in circulation answers "what did this application vendor in".
None of them answers "what built it" -- the compiler, the interpreter, the
package manager, the container engine, the operating system. That second list
is what changes a reproducible build into an unreproducible one, and it is the
list nobody records.

It is also the list regulation is moving toward. The Cyber Resilience Act's
SBOM obligations arrive in December 2027, and "the software this shipped with"
and "the machine it was built on" are separate questions that separate
auditors ask.

CycloneDX rather than a bespoke format because an evidence file nobody's tooling
can read is not evidence. The `data` component type exists in the specification
for precisely this: things that are part of a system without being libraries it
links against.

**Paths never appear.** An executable path names a user's home directory --
on every platform -- and a BOM is an artefact people attach to compliance
tickets and hand to auditors outside their company. What matters for
reproducibility is the *provenance* -- installed by the OS package manager, by a
version manager, by a vendor installer -- and that is recorded instead. This is
the same decision as the container socket in `devrepro.containers.engine`, made
for the same reason.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from devrepro.core.models import ScanReport

__all__ = ["CYCLONEDX_SPEC_VERSION", "purl_for", "render_environment_bom"]

CYCLONEDX_SPEC_VERSION = "1.6"

#: Tools whose upstream identity is well-known enough for a `pkg:generic` PURL
#: to mean something. A PURL that resolves to nothing is worse than no PURL:
#: it invites a scanner to look the component up and report an absence.
_PURL_NAMES: frozenset[str] = frozenset(
    {
        "python",
        "node",
        "go",
        "rustc",
        "cargo",
        "java",
        "dotnet",
        "ruby",
        "php",
        "perl",
        "git",
        "docker",
        "podman",
        "kubectl",
        "npm",
        "pnpm",
        "yarn",
        "bun",
        "pip",
        "uv",
        "poetry",
        "gcc",
        "clang",
        "cmake",
        "make",
    }
)

#: How a tool arrived, mapped to a sentence an auditor reads the same way twice.
#:
#: The keys are the exact values `_install_source` in the toolchain probe emits.
#: The first version of this table invented its own vocabulary -- names like
#: `system-package-manager` that nothing produces -- so every component in the
#: BOM described itself as "provenance could not be determined" while the
#: report beside it knew perfectly well. A lookup table whose keys come from
#: somewhere else has to be checked against that somewhere else, and there is a
#: test below that does.
_PROVENANCE: dict[str, str] = {
    "distro": "Installed by the operating system package manager",
    "system-local": "Installed into /usr/local by an administrator or a build",
    "official-installer": "Installed by a vendor installer",
    "docker-desktop": "Part of a Docker Desktop installation",
    "vs-installer": "Installed by the Visual Studio installer",
    "brew": "Installed by Homebrew",
    "scoop": "Installed by Scoop",
    "choco": "Installed by Chocolatey",
    "conda": "Installed by conda",
    "rustup": "Installed by rustup",
    "pyenv": "Installed by pyenv, a version manager",
    "nvm": "Installed by nvm, a version manager",
    "fnm": "Installed by fnm, a version manager",
    "volta": "Installed by Volta, a version manager",
    "mise": "Installed by mise, a version manager",
    "asdf": "Installed by asdf, a version manager",
    "store-alias": "A Windows App Execution Alias, not a real installation",
    "unknown": "Provenance could not be determined from the installation path",
}


def purl_for(name: str, version: str | None) -> str | None:
    """A package URL for a toolchain component, or None when it would be noise.

    `pkg:generic` is the correct namespace: these are not packages from any one
    registry, and claiming `pkg:pypi/python` would be false -- CPython is not a
    PyPI package. A version is required, because a PURL without one identifies
    nothing that can be checked.
    """
    if not version or name.lower() not in _PURL_NAMES:
        return None
    return f"pkg:generic/{name.lower()}@{version}"


def _bom_ref(kind: str, name: str, version: str | None) -> str:
    """A stable identifier for a component within one BOM.

    Derived from the component's own identity rather than from a counter, so
    two BOMs of the same machine produce the same refs and a diff of them shows
    what changed rather than everything having shifted by one.
    """
    digest = hashlib.sha256(f"{kind}:{name}:{version or ''}".encode()).hexdigest()[:16]
    return f"{kind}-{name.lower().replace(' ', '-')}-{digest}"


def _properties(pairs: dict[str, str | None]) -> list[dict[str, str]]:
    """CycloneDX `properties`, which is how anything non-standard is carried.

    Namespaced under `devrepro:` as the specification asks, so a consumer can
    tell what it can rely on from what this project invented.
    """
    return [
        {"name": f"devrepro:{key}", "value": str(value)}
        for key, value in pairs.items()
        if value is not None and str(value) != ""
    ]


def _serial_number(report: ScanReport) -> str:
    """A deterministic URN, so re-rendering the same report is byte-identical.

    A random UUID would be more conventional and would make every regeneration
    a diff, which defeats the point of an artefact meant to be compared across
    machines and across time.
    """
    seed = f"{report.created_at.isoformat()}|{report.devrepro_version}|{len(report.tools)}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return f"urn:uuid:{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _tool_components(report: ScanReport) -> list[dict[str, Any]]:
    """One component per *active* installation.

    Deliberately not one per resolved path. A machine with three Pythons on
    PATH runs one of them, and a BOM claiming the environment contains three
    Python 3.x installations describes a fact about PATH rather than about the
    build. The others are still recorded -- as a property saying how many were
    found -- because "there were three and this is the one that won" is the
    part a reproducibility question turns on.
    """
    by_name: dict[str, list[Any]] = {}
    for tool in report.tools:
        by_name.setdefault(tool.name, []).append(tool)

    components: list[dict[str, Any]] = []
    for name in sorted(by_name):
        installs = by_name[name]
        active = next((t for t in installs if t.is_active and t.version), None)
        active = active or next((t for t in installs if t.version), None) or installs[0]
        if not active.version:
            # A component with no version identifies nothing. Recording it
            # would put a row in an evidence file that cannot be verified.
            continue

        source = (active.install_source or "unknown").lower()
        component: dict[str, Any] = {
            "type": "application",
            "bom-ref": _bom_ref("tool", name, active.version),
            "name": name,
            "version": active.version,
            "scope": "required",
            "description": _PROVENANCE.get(source, _PROVENANCE["unknown"]),
            "properties": _properties(
                {
                    "install-source": active.install_source,
                    "installations-found": str(len(installs)) if len(installs) > 1 else None,
                }
            ),
        }
        purl = purl_for(name, active.version)
        if purl:
            component["purl"] = purl
        components.append(component)
    return components


def _platform_component(report: ScanReport) -> dict[str, Any]:
    """The machine itself, as the subject the BOM is about.

    `type: platform` is what CycloneDX 1.6 provides for "the thing everything
    else runs on". Naming it `host` rather than the hostname is deliberate: a
    hostname is frequently a person's name or a project codename, and this
    file leaves the machine.
    """
    platform = report.platform
    return {
        "type": "platform",
        "bom-ref": _bom_ref("platform", "host", platform.os_version),
        "name": "host",
        "version": platform.os_version,
        "description": f"{platform.os_name} {platform.os_version} ({platform.arch})",
        "properties": _properties(
            {
                "os-name": platform.os_name,
                "os-version": platform.os_version,
                "architecture": platform.arch,
                "kernel": getattr(platform, "kernel", None),
            }
        ),
    }


def _container_component(report: ScanReport) -> dict[str, Any] | None:
    """The container engine, when one answered.

    A build that runs in a container is reproduced by the engine as much as by
    the compiler, and the engine's identity -- Docker Desktop, Colima, a native
    daemon -- changes bind-mount behaviour and file-sharing semantics.
    """
    containers = report.containers
    if containers is None or not containers.server_version:
        return None
    return {
        "type": "platform",
        "bom-ref": _bom_ref("engine", containers.backend or "container", containers.server_version),
        "name": containers.backend or "container-engine",
        "version": containers.server_version,
        "description": "Container engine available to this environment",
        "properties": _properties(
            {
                "storage-driver": containers.storage_driver,
                "cgroup-version": containers.cgroup_version,
                "server-architecture": containers.server_arch,
                "rootless": str(containers.rootless) if containers.rootless is not None else None,
            }
        ),
    }


def render_environment_bom(report: ScanReport, *, indent: int = 2) -> str:
    """Render a CycloneDX 1.6 BOM describing the environment.

    Deterministic: the same report renders byte-identically, including the
    serial number, so two machines' BOMs diff cleanly and a regenerated one
    does not look like a change.
    """
    from devrepro import __version__

    components = [_platform_component(report)]
    engine = _container_component(report)
    if engine:
        components.append(engine)
    components.extend(_tool_components(report))

    bom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": _serial_number(report),
        "version": 1,
        "metadata": {
            "timestamp": report.created_at.isoformat(),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "devrepro-doctor",
                        "version": __version__,
                        "description": (
                            "Environment bill of materials: the toolchain a build runs on, "
                            "not the dependencies it links against."
                        ),
                    }
                ]
            },
            "component": components[0],
            "properties": _properties(
                {
                    "scan-schema-version": report.schema_version,
                    "note": (
                        "Executable paths are deliberately absent: they contain usernames, "
                        "and this file is shared outside the machine that produced it."
                    ),
                }
            ),
        },
        # The platform is the metadata subject *and* the first component, which
        # is how CycloneDX expresses "this BOM is about that thing".
        "components": components[1:],
    }
    return json.dumps(bom, indent=indent, sort_keys=False, ensure_ascii=False) + chr(10)
