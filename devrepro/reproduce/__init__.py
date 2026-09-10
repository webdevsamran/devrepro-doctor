"""Turning a reported failure into something somebody else can run.

`recipe` builds the model, `emit` renders it into the formats people run,
`adapters` hands it to a sandbox they already pay for, `bisect` narrows a
forty-line environment diff to the dimension that matters, and `corpus` records
how often any of it actually works.

Every one of them stops short of executing anything. Building an image
downloads gigabytes and running the failing command executes what the project
told us to execute; both are the user's decision, and the recipe is the
artefact.
"""

from __future__ import annotations

from devrepro.reproduce.adapters import ADAPTERS, render_adapter
from devrepro.reproduce.bisect import (
    BisectResult,
    Dimension,
    MinimisationResult,
    bisect_dimensions,
    minimise_dimensions,
)
from devrepro.reproduce.corpus import (
    OUTCOMES,
    Attempt,
    CorpusSummary,
    read_corpus,
    record_attempt,
    summarise,
)
from devrepro.reproduce.emit import (
    EMIT_FORMATS,
    render_compose,
    render_devcontainer,
    render_dockerfile,
    render_nix_flake,
    render_repro_script,
    strip_provenance,
)
from devrepro.reproduce.recipe import (
    BASE_IMAGES,
    Precondition,
    Reproduction,
    SetupStep,
    build_reproduction,
)

__all__ = [
    "ADAPTERS",
    "BASE_IMAGES",
    "EMIT_FORMATS",
    "OUTCOMES",
    "Attempt",
    "BisectResult",
    "CorpusSummary",
    "Dimension",
    "MinimisationResult",
    "Precondition",
    "Reproduction",
    "SetupStep",
    "bisect_dimensions",
    "build_reproduction",
    "minimise_dimensions",
    "read_corpus",
    "record_attempt",
    "render_adapter",
    "render_compose",
    "render_devcontainer",
    "render_dockerfile",
    "render_nix_flake",
    "render_repro_script",
    "strip_provenance",
    "summarise",
]
