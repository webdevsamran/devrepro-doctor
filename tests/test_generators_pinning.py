"""Generated environment files must be valid, installable and pinned.

`generate mise` emitted this on a real project:

    [tools]
    ci:python = ""3.12""
    tomli = "2.0; python_version < '3.11'"

That is not valid TOML, and two of the entries are not tools. A generator whose
output does not parse is worse than no generator: the reader trusts it, commits
it, and finds out later.
"""

from __future__ import annotations

import json
import tomllib

import pytest
from devrepro.core.runner import CommandResult, RecordingRunner
from devrepro.generators import (
    DEFAULT_DEVCONTAINER_IMAGE,
    features_for,
    generate_devcontainer,
    generate_tool_versions,
    normalise_pin,
    resolve_image_digest,
)

# ------------------------------------------------------------ pin normalising


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (">=3.11", "3.11"),
        ("^22.1.0", "22.1.0"),
        ("~1.2.3", "1.2.3"),
        ('"3.12"', "3.12"),  # quotes already present in the source document
        ("2.0; python_version < '3.11'", "2.0"),  # PEP 508 marker
        ("9.7.7,<9.8", "9.7.7"),  # a range cannot be installed
        ("*", None),
        ("", None),
        ("file:../local", None),
        ("latest", None),
    ],
)
def test_pins_are_normalised_to_something_installable(spec: str, expected: str | None) -> None:
    assert normalise_pin(spec) == expected


# --------------------------------------------------------------- mise / asdf


def _requirements() -> dict[str, str]:
    """Shaped like what `detect_requirements` really returns for this repo."""
    return {
        "python": ">=3.11",
        "node": "^22.1.0",
        "ci:python": '"3.12"',  # a CI declaration, not a tool
        "pydantic": "2.6,<3.0",  # a library, not a runtime
        "tomli": "2.0; python_version < '3.11'",
        "mkdocs-material": "9.7.7,<9.8",
    }


def test_generated_mise_config_is_valid_toml() -> None:
    """The regression this file exists for."""
    content = generate_tool_versions(_requirements(), style="mise")
    parsed = tomllib.loads(content)
    assert parsed["tools"] == {"python": "3.11", "node": "22.1.0"}


def test_libraries_and_ci_entries_are_not_offered_as_tools() -> None:
    """A version manager cannot install `pydantic`, and `ci:python` is a record."""
    content = generate_tool_versions(_requirements(), style="mise")
    for absent in ("pydantic", "mkdocs-material", "tomli", "ci:"):
        assert absent not in content


def test_asdf_output_lists_one_runtime_per_line() -> None:
    content = generate_tool_versions(_requirements(), style="asdf")
    entries = [line.split() for line in content.splitlines() if line and not line.startswith("#")]
    assert entries == [["node", "22.1.0"], ["python", "3.11"]]


def test_nothing_to_pin_says_so_rather_than_emitting_an_empty_table() -> None:
    """An empty `[tools]` reads like a mistake; a sentence does not."""
    content = generate_tool_versions({"pydantic": "2.6"}, style="mise")
    assert tomllib.loads(content)["tools"] == {}
    assert "No managed runtime versions" in content


# ------------------------------------------------------------- devcontainer


def test_an_unpinned_image_says_so_in_the_file() -> None:
    """A mutable tag in a reproducibility artefact must announce itself."""
    payload = json.loads(generate_devcontainer())
    assert payload["image"] == DEFAULT_DEVCONTAINER_IMAGE
    assert "mutable" in payload["//pinning"]


def test_a_digest_replaces_the_tag_and_drops_the_warning() -> None:
    digest = "mcr.microsoft.com/devcontainers/base@sha256:" + "a" * 64
    payload = json.loads(generate_devcontainer(digest=digest))
    assert payload["image"] == digest
    assert "//pinning" not in payload


def test_features_follow_the_detected_requirements() -> None:
    """A devcontainer that installs nothing the project needs gets deleted."""
    payload = json.loads(
        generate_devcontainer(requirements={"python": ">=3.11", "node": "22", "pydantic": "2"})
    )
    features = payload["features"]
    assert features["ghcr.io/devcontainers/features/python:1"] == {"version": "3.11"}
    assert features["ghcr.io/devcontainers/features/node:1"] == {"version": "22"}
    # A library is not a devcontainer feature.
    assert not any("pydantic" in key for key in features)


def test_no_requirements_means_no_features_block() -> None:
    assert "features" not in json.loads(generate_devcontainer())


def test_features_for_ignores_unknown_names() -> None:
    assert features_for({"some-internal-tool": "1.0"}) == {}


# ------------------------------------------------------------ digest lookup


def test_digest_is_resolved_through_the_local_docker_cli() -> None:
    """Not an HTTP call: the user's registry auth and mirrors live in docker."""
    sha = "sha256:" + "b" * 64
    runner = RecordingRunner({"docker": CommandResult(("docker",), 0, sha + chr(10), "")})
    resolved = resolve_image_digest("example.com/base:1.0", runner)
    assert resolved == f"example.com/base@{sha}"


def test_a_missing_docker_yields_no_digest_rather_than_an_error() -> None:
    """Pinning improves the output; it is not a precondition for producing it."""
    assert resolve_image_digest("example.com/base:1.0", RecordingRunner()) is None


def test_a_nonsense_response_is_not_treated_as_a_digest() -> None:
    runner = RecordingRunner({"docker": CommandResult(("docker",), 0, "not a digest", "")})
    assert resolve_image_digest("example.com/base:1.0", runner) is None
