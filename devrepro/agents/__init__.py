"""Agent-readiness: can a coding agent actually work in this repository?

Coding agents read a manifest -- `AGENTS.md`, `CLAUDE.md`, `.cursorrules` --
and follow the commands it declares. Nothing checks those commands against the
machine the agent is running on, so an agent discovers a missing binary or a
stale instruction the expensive way: by running it, failing, and guessing.

Two questions are answered here, and both are read-only by default:

* **Do the declared commands resolve on this machine?** A program that is
  installed but not on PATH in this shell is a different problem from one that
  is not installed, and an agent cannot currently tell those apart.
* **Does the manifest match what CI enforces?** A manifest that lists a subset
  of the real gates is worse than none: the agent runs everything it was told
  to, sees green, and is failed by checks nobody mentioned.

Nothing here executes a declared command unless explicitly asked. A manifest is
an untrusted file in someone else's repository, and its "setup" step is
typically an installer that writes to disk and fetches from the network.
Running that by default would make the project's read-only promise conditional
on what a third-party file happened to say, so execution sits behind an opt-in
flag, mirroring `network --allow-network` and `fix --yes`.
"""

from __future__ import annotations

from devrepro.agents.blast_radius import BlastRadius, Exposure, assess_blast_radius
from devrepro.agents.manifest import (
    AGENT_MANIFESTS,
    AgentManifest,
    CommandCheck,
    DeclaredCommand,
    check_declared_commands,
    ci_declared_commands,
    discover_manifests,
    manifest_vs_ci,
    parse_declared_commands,
)

__all__ = [
    "AGENT_MANIFESTS",
    "AgentManifest",
    "BlastRadius",
    "CommandCheck",
    "DeclaredCommand",
    "Exposure",
    "assess_blast_radius",
    "check_declared_commands",
    "ci_declared_commands",
    "discover_manifests",
    "manifest_vs_ci",
    "parse_declared_commands",
]
