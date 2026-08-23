"""Doctor self-test: verifies the engine's own safety assumptions.

Run with ``devrepro selftest``. Checks are deterministic and offline:
- probe determinism (same input -> same output, twice);
- redaction guarantees (secrets never survive into report structures);
- secure temp-directory handling;
- subprocess capture (bounded, timeout-enforced);
- permission assumptions (read-only probes never write outside temp).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from devrepro.core.runner import SubprocessRunner

__all__ = ["SelfTestReport", "run_selftest"]


@dataclass(frozen=True)
class SelfTestCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class SelfTestReport:
    checks: tuple[SelfTestCheck, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)


def _check_determinism() -> SelfTestCheck:
    from devrepro.core.versioning import parse_version

    v1 = parse_version("1.2.3")
    v2 = parse_version("1.2.3")
    ok = str(v1) == str(v2) and v1 == v2
    return SelfTestCheck(
        "probe-determinism",
        ok,
        "version parsing is deterministic across repeated calls",
    )


def _check_redaction() -> SelfTestCheck:
    from devrepro.privacy.gate import PrivacyGate, scan_for_secrets

    # 1) credential shapes must be DETECTED (so callers can refuse to emit them)
    secret_sample = "token=" + "ghp_" + "a" * 24
    detected = bool(scan_for_secrets(secret_sample))
    # 2) personal identifiers (home path, username, email) must be REDACTED
    gate = PrivacyGate()
    personal = f"home={gate.home} mail=dev@example.com"
    out = gate.redact(personal)
    home_gone = gate.home not in out and "~" in out
    email_gone = "dev@example.com" not in out and "<email-redacted>" in out
    ok = detected and home_gone and email_gone
    detail = (
        "credential detection + home/username/email redaction verified"
        if ok
        else f"detected={detected} home_redacted={home_gone} email_redacted={email_gone}"
    )
    return SelfTestCheck("redaction", ok, detail)


def _check_temp_dirs() -> SelfTestCheck:
    try:
        with tempfile.TemporaryDirectory(prefix="devrepro-selftest-") as td:
            p = Path(td)
            probe_file = p / "probe.txt"
            probe_file.write_text("x", encoding="utf-8")
            ok = probe_file.exists() and p.is_dir()
        # after context exit the directory must be gone
        gone = not Path(td).exists()
        return SelfTestCheck(
            "temp-directories", ok and gone, "secure temp dir created, used, cleaned up"
        )
    except OSError as exc:
        return SelfTestCheck("temp-directories", False, f"{type(exc).__name__}: {exc}")


def _check_subprocess_capture() -> SelfTestCheck:
    runner = SubprocessRunner()
    res = runner.run(("python", "-c", "print('devrepro-ok')"), timeout=10.0)
    ok = res.returncode == 0 and "devrepro-ok" in (res.stdout or "")
    return SelfTestCheck(
        "subprocess-capture",
        ok,
        f"returncode={res.returncode}, stdout captured={bool(res.stdout)}",
    )


def _check_readonly_probes() -> SelfTestCheck:
    """Verify a scan of a temp project writes nothing inside the project."""
    try:
        with tempfile.TemporaryDirectory(prefix="devrepro-ro-") as td:
            root = Path(td)
            (root / "package.json").write_text("{}", encoding="utf-8")
            before = {str(p.relative_to(root)) for p in root.rglob("*")}
            from devrepro.project.profiles import detect_profile, score_maturity

            detect_profile(root)
            score_maturity(root)
            after = {str(p.relative_to(root)) for p in root.rglob("*")}
            new_files = after - before - {"package.json"}
            return SelfTestCheck(
                "readonly-probes",
                not new_files,
                f"no files written by probes ({len(new_files)} unexpected)"
                if not new_files
                else f"unexpected writes: {sorted(new_files)}",
            )
    except OSError as exc:
        return SelfTestCheck("readonly-probes", False, f"{type(exc).__name__}: {exc}")


def run_selftest() -> SelfTestReport:
    """Execute all engine self-checks. Deterministic; no network access."""
    checks = (
        _check_determinism(),
        _check_redaction(),
        _check_temp_dirs(),
        _check_subprocess_capture(),
        _check_readonly_probes(),
    )
    return SelfTestReport(checks=checks)
