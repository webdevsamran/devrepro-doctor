"""The secret scanner must actually catch secrets.

A scanner that returns clean is indistinguishable from a scanner that checks
nothing, which is the failure mode this repository has already shipped twice
elsewhere: a CI step named for a validation it never performed, and a schema
gate that validated the schema document instead of any artifact.

So the scanner is tested the only way that means anything -- by planting a
real-shaped secret of each class it claims to detect and asserting it is
found. Writing this test found that the pattern list had no Slack, Google,
Stripe or npm rule at all, and that a placeholder heuristic was suppressing a
real-shaped npm token because it happened to end in `0123456789`.

Nothing here is a real credential. Every value is synthetic, and the two the
scanner deliberately ignores are asserted as ignored so the exemptions stay
narrow.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _scanner() -> Any:
    """Import scripts/secret_scan.py, which is not an importable package."""
    path = _ROOT / "scripts" / "secret_scan.py"
    spec = importlib.util.spec_from_file_location("secret_scan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matches(module: Any, text: str) -> list[str]:
    """Rule names that fire on `text`, after the synthetic-value filter."""
    hits = []
    for name, pattern in module.PATTERNS:
        for match in pattern.finditer(text):
            snippet = match.group(0)
            if any(a in snippet.lower() for a in module.ALLOW_SUBSTRINGS):
                continue
            if module.looks_synthetic(snippet):
                continue
            hits.append(name)
    return hits


#: Synthetic but correctly shaped. Each must trip at least one rule.
#:
#: Assembled from fragments rather than written as whole literals. GitHub's
#: push protection rejected an earlier version of this file -- it read the
#: Slack fixture as a live Slack API token and blocked the push outright.
#: That is the correct behaviour on its side and useful evidence on ours: these
#: values are realistic enough for a real scanner to bite. The offered
#: "allow this secret" URL was the wrong door to walk through; a repository
#: that learns to wave detections away has lost the gate. Joining fragments at
#: runtime keeps the test exercising a fully-formed value while leaving no
#: complete credential-shaped literal in the tree for anyone's scanner --
#: GitHub's, ours, or a future one -- to trip over.
def _j(*parts: str) -> str:
    return "".join(parts)


MUST_DETECT = {
    "github-pat": 'TOKEN = "' + _j("ghp_", "16C7e42F292c6912E7710c838347Ae178B4a") + '"',
    "openai": 'KEY = "' + _j("sk-", "proj9vQx2LmZ8pT4wR7yK1nB3cV6hJ0sD5fG8aE2uI4oP") + '"',
    "aws": 'AWS = "' + _j("AKIA", "3KJHF8SDLKJ2HF9X") + '"',
    "slack": 'SLACK = "' + _j("xox", "b-2734982374-2938749283-KJHfkjhdsfKJHDSF") + '"',
    "google": 'G = "' + _j("AIza", "SyD3kJhGf8sLkJhGf8sLkJhGf8sLkJhGf8s") + '"',
    "stripe": 'S = "' + _j("sk_", "live_4eC39HqLyjWDarjtT1zdp7dc") + '"',
    "npm": 'N = "' + _j("npm_", "aB3dEfGhIjKlMnOpQrStUvWxYz0123456789") + '"',
    "private-key": 'PEM = "' + _j("-----BEGIN ", "RSA PRIVATE KEY-----") + '"',
    "password": 'password = "' + _j("Tr0ub4dor", "&3xKcd9zQ") + '"',
    # Added because test_every_pattern_is_exercised_by_this_file caught that
    # `bearer-token` had only a *suppressed* fixture and no positive case.
    "bearer": 'H = "Authorization: '
    + _j("Bearer ", "eyJhbGciOiJIUzI1NiJ9.RkQ7mVn2pXt.9fQ2wZ")
    + '"',
}

#: Values this repository legitimately contains that must NOT be reported.
MUST_IGNORE = {
    "placeholder-in-docs": 'key = "your-api-key-here"',
    "spaced-non-credential": 'write_text("token: " + TOKEN, encoding="utf-8")',
}


@pytest.mark.parametrize("label", sorted(MUST_DETECT))
def test_a_real_shaped_secret_of_each_class_is_detected(label: str) -> None:
    module = _scanner()
    hits = _matches(module, MUST_DETECT[label])
    assert hits, (
        f"a real-shaped {label} secret passed the scanner unreported. "
        "Either the pattern is missing or a placeholder heuristic is too broad."
    )


@pytest.mark.parametrize("label", sorted(MUST_IGNORE))
def test_the_repositorys_own_fixtures_are_not_reported(label: str) -> None:
    module = _scanner()
    assert not _matches(module, MUST_IGNORE[label]), (
        f"{label} is a fixture demonstrating credential handling, not a credential; "
        "reporting it trains people to ignore this gate"
    )


def test_the_synthetic_filter_needs_a_dominant_run_not_merely_a_run() -> None:
    """A real token that happens to contain `0123456789` must survive.

    The first version of this heuristic suppressed any value containing a
    six-character ascending run, which hid a real-shaped npm token outright.
    """
    module = _scanner()
    fixture = '"sk-abcdefghijklmnop1234"'  # secret-scan: allow
    real_shaped_value = '"npm_aB3dEfGhIjKlMnOpQrStUvWxYz0123456789"'  # secret-scan: allow
    assert module.looks_synthetic(fixture)
    assert not module.looks_synthetic(real_shaped_value)


def test_every_pattern_is_exercised_by_this_file() -> None:
    """A rule nobody tests is a rule nobody knows works."""
    module = _scanner()
    exercised = set()
    for text in MUST_DETECT.values():
        exercised.update(_matches(module, text))
    declared = {name for name, _ in module.PATTERNS}
    untested = sorted(declared - exercised)
    assert not untested, f"these detection rules have no test: {untested}"


def test_the_scanner_reports_a_path_and_line() -> None:
    """A finding a reader cannot locate is not actionable."""
    source = (_ROOT / "scripts" / "secret_scan.py").read_text(encoding="utf-8")
    assert re.search(r"\{rel\}:\{line_no\}", source), (
        "secret_scan.py no longer reports file:line for a finding"
    )
