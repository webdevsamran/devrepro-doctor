"""cpp rule pack: compilers + build tools required by C/C++ projects."""

from __future__ import annotations

from devrepro.core.models import Evidence, Finding, FindingState
from devrepro.rules.base import RuleContext
from devrepro.rules.packs.common import requirement_for, runtime_findings

__all__ = ["evaluate"]


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    cpp_reqs = [r for r in ctx.requirements if r.ecosystem == "cpp"]
    if not cpp_reqs:
        return findings

    cmake_req = requirement_for(ctx, "cpp", "cmake")
    if cmake_req is not None:
        findings.extend(runtime_findings(ctx, pack="cpp", tool="cmake"))

    has_compiler = any(t.name in ("gcc", "clang", "cl") for t in ctx.tools)
    if not has_compiler:
        findings.append(
            Finding(
                rule_id="cpp/no-compiler",
                state=FindingState.BLOCKED,
                summary="C/C++ project present but no compiler (gcc/clang/MSVC cl) found on PATH.",
                evidence=(Evidence(source="command", excerpt="checked gcc, clang, cl on PATH"),),
                component="cpp",
                remediation_hint="Install a toolchain: MSVC Build Tools (Windows), "
                "build-essential (Debian/Ubuntu), Xcode CLT (macOS).",
            )
        )
    return findings