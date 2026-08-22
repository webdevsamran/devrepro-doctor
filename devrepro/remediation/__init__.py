"""Safe remediation."""

from __future__ import annotations

from devrepro.remediation.planner import AUTOMATABLE_RISKS, build_plan, execute_plan

__all__ = ["AUTOMATABLE_RISKS", "build_plan", "execute_plan"]