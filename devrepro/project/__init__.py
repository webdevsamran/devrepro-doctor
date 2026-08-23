"""Project requirement detection and policy."""

from __future__ import annotations

from devrepro.project.detectors import detect_project_kind, detect_requirements
from devrepro.project.policy import POLICY_FILENAME, load_policy

__all__ = ["POLICY_FILENAME", "detect_project_kind", "detect_requirements", "load_policy"]
