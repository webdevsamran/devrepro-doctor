"""Privacy engine: redaction + secret scanning.

Every serialized artifact (snapshot, report, diff export) passes through
:func:`redact` before leaving the process, and :func:`assert_no_secrets`
blocks export entirely when probable credentials are detected.

Redacts:
- usernames (account name of the current user)
- home directory absolute paths
- email addresses
- tokens/API keys by pattern (AWS, GitHub, OpenAI-style, JWT, Bearer,
  generic high-entropy assignments, PEM blocks)

Never redacts tool names or versions — only personal/secret material.
"""

from __future__ import annotations

import getpass
import os
import re
from pathlib import Path

from devrepro.core.errors import PrivacyViolationError

__all__ = ["PrivacyGate", "assert_no_secrets", "redact", "scan_for_secrets"]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("openai-style-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}")),
    (
        "private-key-block",
        re.compile("-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY( BLOCK)?-----"),
    ),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password|passwd|credential)"
            r"\s*[=:]\s*\S{8,}"
        ),
    ),
)


class PrivacyGate:
    """Configurable redaction context for one scan."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        username: str | None = None,
        extra_hosts: tuple[str, ...] = (),
    ) -> None:
        self.home = str(home or Path.home())
        self.username = username or _safe_user()
        self.extra_hosts = extra_hosts
        self._home_variants = {
            self.home,
            self.home.replace(chr(92), "/"),
            self.home.replace("/", chr(92)),
            os.path.normcase(self.home),
        }

    def redact(self, text: str) -> str:
        out = text
        # home paths first (longest match wins naturally)
        for variant in sorted(self._home_variants, key=len, reverse=True):
            if variant and variant in out:
                out = out.replace(variant, "~")
        # username as a path component / bare word
        if self.username:
            out = re.sub(
                r"(?<![A-Za-z0-9_])" + re.escape(self.username) + r"(?![A-Za-z0-9_])",
                "<user>",
                out,
            )
        # emails
        out = _EMAIL_RE.sub("<email-redacted>", out)
        # configured private hosts
        for host in self.extra_hosts:
            out = re.sub(re.escape(host), "<private-host>", out, flags=re.IGNORECASE)
        return out

    def redact_mapping(self, data: dict[str, object]) -> dict[str, object]:
        return {k: self.redact(str(v)) for k, v in data.items()}


def _safe_user() -> str:
    try:
        name = getpass.getuser()
        return name if name and name != "unknown" else ""
    except Exception:
        return ""


def redact(text: str) -> str:
    """Convenience one-shot redaction with default context."""
    return PrivacyGate().redact(text)


def scan_for_secrets(text: str) -> list[str]:
    """Return the kinds of probable secrets found in ``text``."""
    found: list[str] = []
    for kind, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            found.append(kind)
    return found


def assert_no_secrets(text: str) -> None:
    """Raise PrivacyViolationError if probable secrets are present."""
    found = scan_for_secrets(text)
    if found:
        raise PrivacyViolationError(
            f"Probable secret(s) detected in output ({', '.join(found)}); "
            "export blocked to protect your machine.",
            hint="Remove the secret from the source (env var/config) and re-run.",
        )
