"""Package sources and per-runtime certificate trust.

Two failures that look like network problems and are configuration problems: a
registry override means two developers get packages from different places, and
a TLS trust store fixed for one runtime leaves every other one failing, because
each ecosystem reads its own variable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.network.registries import (
    CA_BUNDLE_VARS,
    detect_registries,
    detect_trust_stores,
    ecosystems_without_custom_trust,
    strip_credentials,
)

if TYPE_CHECKING:
    from pathlib import Path

NL = chr(10)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------- credentials


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:token@npm.corp.com/", "https://<redacted>@npm.corp.com/"),
        ("https://tok@pypi.corp/simple", "https://<redacted>@pypi.corp/simple"),
        ("https://registry.npmjs.org/", "https://registry.npmjs.org/"),
        ("http://localhost:4873/", "http://localhost:4873/"),
    ],
)
def test_credentials_are_stripped_from_urls(url: str, expected: str) -> None:
    """`.npmrc` routinely carries an auth token inline.

    A diagnostic report exists to be pasted into an issue, so a credential must
    not survive contact with it.
    """
    assert strip_credentials(url) == expected


def test_a_token_never_reaches_a_reported_registry(tmp_path: Path) -> None:
    token = "npm_" + ("z" * 30)
    _write(tmp_path / ".npmrc", f"registry=https://ci:{token}@npm.corp.example/{NL}")

    found = detect_registries(tmp_path, home=tmp_path / "nonexistent-home")

    assert found, "the registry was not detected at all"
    assert all(token not in r.url for r in found), "a token reached the report"
    assert "<redacted>" in found[0].url


# -------------------------------------------------------------- registries


def test_an_npm_registry_override_is_detected(tmp_path: Path) -> None:
    _write(tmp_path / ".npmrc", "registry=https://npm.corp.example/" + NL)
    found = detect_registries(tmp_path, home=tmp_path / "no-home")
    assert [(r.ecosystem, r.scope) for r in found] == [("npm", "project")]
    assert not found[0].is_default


def test_the_public_registry_is_recognised_as_default(tmp_path: Path) -> None:
    _write(tmp_path / ".npmrc", "registry=https://registry.npmjs.org/" + NL)
    assert detect_registries(tmp_path, home=tmp_path / "no-home")[0].is_default


def test_a_pip_index_override_is_detected(tmp_path: Path) -> None:
    _write(tmp_path / "pip.conf", "[global]" + NL + "index-url = https://pypi.corp/simple" + NL)
    found = detect_registries(tmp_path, home=tmp_path / "no-home")
    assert found[0].ecosystem == "pip"
    assert "pypi.corp" in found[0].url


def test_user_scope_is_distinguished_from_project_scope(tmp_path: Path) -> None:
    """A user-level file is invisible to everyone else on the team.

    It is the one that explains why the same command behaves differently on two
    machines, so the scope has to be reported, not just the URL.
    """
    project = tmp_path / "project"
    home = tmp_path / "home"
    _write(project / ".npmrc", "registry=https://team.example/" + NL)
    _write(home / ".npmrc", "registry=https://personal.example/" + NL)

    found = detect_registries(project, home=home)

    by_scope = {r.scope: r.url for r in found}
    assert "team.example" in by_scope["project"]
    assert "personal.example" in by_scope["user"]


def test_a_scoped_npm_registry_is_detected(tmp_path: Path) -> None:
    _write(tmp_path / ".npmrc", "@acme:registry=https://npm.acme.example/" + NL)
    assert detect_registries(tmp_path, home=tmp_path / "no-home")[0].ecosystem == "npm"


def test_a_project_with_no_overrides_reports_nothing(tmp_path: Path) -> None:
    assert detect_registries(tmp_path, home=tmp_path / "no-home") == []


# ------------------------------------------------------------ trust stores


def test_a_custom_ca_bundle_is_detected(tmp_path: Path) -> None:
    bundle = tmp_path / "corp-ca.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

    stores = detect_trust_stores({"NODE_EXTRA_CA_CERTS": str(bundle)})

    assert len(stores) == 1
    assert stores[0].ecosystem == "node"
    assert stores[0].exists is True


def test_a_ca_bundle_pointing_at_a_missing_file_is_reported_as_such() -> None:
    """A variable set to a path that does not exist fails silently at runtime."""
    stores = detect_trust_stores({"REQUESTS_CA_BUNDLE": "/no/such/bundle.pem"})
    assert stores[0].exists is False


def test_no_custom_trust_means_nothing_to_report() -> None:
    assert detect_trust_stores({"PATH": "/usr/bin"}) == []


def test_ecosystems_missing_a_custom_ca_are_named() -> None:
    """The finding that matters behind an intercepting proxy.

    Fixing Node and leaving Python is the common half-configured state: one
    toolchain installs, the other fails with a certificate error that names the
    certificate rather than the missing variable.
    """
    missing = ecosystems_without_custom_trust({"NODE_EXTRA_CA_CERTS": "/etc/corp.pem"})

    assert "node" not in missing
    assert "python" in missing
    assert "go" in missing


def test_nothing_configured_means_no_complaint() -> None:
    """A machine with no proxy is not half-configured; it is fine."""
    assert ecosystems_without_custom_trust({"PATH": "/usr/bin"}) == []


def test_every_ecosystem_lists_at_least_one_variable() -> None:
    for ecosystem, variables in CA_BUNDLE_VARS.items():
        assert variables, f"{ecosystem} has no CA variable listed"
        assert all(v.isupper() for v in variables)
