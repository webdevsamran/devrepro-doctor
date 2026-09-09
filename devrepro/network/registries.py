"""Where packages come from, and which certificates each runtime trusts.

Two failures that look like network problems and are configuration problems.

A registry override -- `.npmrc` pointing at a proxy, `pip.conf` at an internal
mirror -- means two developers running the same install command get packages
from different places. The lockfile matches, the versions match, and the bytes
may not.

A TLS trust store is worse, because every runtime keeps its own. Node reads
`NODE_EXTRA_CA_CERTS`, Python reads `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE`,
Go reads `SSL_CERT_FILE`, Java has a keystore, and git has yet another setting.
Behind a TLS-intercepting proxy, adding the corporate CA to one of them fixes
one toolchain and leaves the rest failing with certificate errors that name the
certificate rather than the missing configuration.

Everything here reads configuration. No connection is made, no credential is
read, and a registry URL carrying an embedded token is reported with the
credential stripped -- `.npmrc` in particular routinely contains one.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from devrepro.probes.helpers import read_text_safe

__all__ = [
    "CA_BUNDLE_VARS",
    "RegistryConfig",
    "TrustStore",
    "detect_registries",
    "detect_trust_stores",
    "strip_credentials",
]

#: Environment variables that point a runtime at a non-default CA bundle. Each
#: ecosystem reads its own, which is why fixing one fixes only one.
CA_BUNDLE_VARS: dict[str, tuple[str, ...]] = {
    "node": ("NODE_EXTRA_CA_CERTS",),
    "python": ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE", "PIP_CERT"),
    "go": ("SSL_CERT_FILE", "SSL_CERT_DIR"),
    "git": ("GIT_SSL_CAINFO", "GIT_SSL_CAPATH"),
    "deno": ("DENO_CERT",),
    "cargo": ("CARGO_HTTP_CAINFO",),
}

_REGISTRY_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("npm", ".npmrc", r"(?m)^\s*(?:@[\w.-]+:)?registry\s*=\s*(\S+)"),
    ("pip", "pip.conf", r"(?m)^\s*(?:index-url|extra-index-url)\s*=\s*(\S+)"),
    ("pip", "pip.ini", r"(?m)^\s*(?:index-url|extra-index-url)\s*=\s*(\S+)"),
    ("uv", "uv.toml", r'(?m)^\s*index-url\s*=\s*"([^"]+)"'),
    ("cargo", ".cargo/config.toml", r'(?m)^\s*replace-with\s*=\s*"([^"]+)"'),
    ("maven", ".m2/settings.xml", r"<url>\s*([^<\s]+)\s*</url>"),
    ("bundler", ".bundle/config", r"BUNDLE_MIRROR__[^:]+:\s*(\S+)"),
    ("composer", ".composer/config.json", r'"url"\s*:\s*"([^"]+)"'),
)

#: A registry URL may carry `user:token@host`. Never report the credential.
_CREDENTIAL_IN_URL = re.compile(r"://[^/@\s]+@")


@dataclass(frozen=True)
class RegistryConfig:
    """A configured package source."""

    ecosystem: str
    source_file: str
    url: str
    scope: str  # "project" | "user"

    @property
    def is_default(self) -> bool:
        defaults = (
            "registry.npmjs.org",
            "pypi.org",
            "crates.io",
            "repo.maven.apache.org",
            "rubygems.org",
            "packagist.org",
        )
        return any(d in self.url for d in defaults)


@dataclass(frozen=True)
class TrustStore:
    """A runtime pointed at a non-default certificate bundle."""

    ecosystem: str
    variable: str
    path: str
    exists: bool


def strip_credentials(url: str) -> str:
    """Remove `user:token@` from a URL before it is reported anywhere.

    `.npmrc` routinely carries an auth token inline. A diagnostic report is
    pasted into issues, so the credential must not survive contact with it.
    """
    return _CREDENTIAL_IN_URL.sub("://<redacted>@", url)


def detect_registries(root: Path | str, *, home: Path | None = None) -> list[RegistryConfig]:
    """Configured package sources, project-level and user-level.

    Both scopes matter and for different reasons: a project file is shared and
    reviewable, a user file is invisible to everyone else and is the one that
    explains why the same command behaves differently on two machines.
    """
    root = Path(root)
    home = home or Path.home()
    found: list[RegistryConfig] = []

    for scope, base in (("project", root), ("user", home)):
        for ecosystem, filename, pattern in _REGISTRY_PATTERNS:
            text = read_text_safe(base / filename)
            if not text:
                continue
            for match in re.findall(pattern, text):
                found.append(
                    RegistryConfig(
                        ecosystem=ecosystem,
                        source_file=filename,
                        url=strip_credentials(str(match).strip()),
                        scope=scope,
                    )
                )
    return found


def detect_trust_stores(env: dict[str, str] | None = None) -> list[TrustStore]:
    """Runtimes pointed at a custom CA bundle.

    Reported per ecosystem rather than as a single fact, because that is how
    the problem actually presents: `npm install` works and `pip install` fails
    on the same machine, behind the same proxy, because only one of the two
    variables was set.
    """
    env = dict(os.environ) if env is None else env
    stores: list[TrustStore] = []
    for ecosystem, variables in CA_BUNDLE_VARS.items():
        for variable in variables:
            value = env.get(variable)
            if not value:
                continue
            stores.append(
                TrustStore(
                    ecosystem=ecosystem,
                    variable=variable,
                    path=value,
                    exists=Path(value).exists(),
                )
            )
    return stores


def ecosystems_without_custom_trust(env: dict[str, str] | None = None) -> list[str]:
    """Ecosystems with no custom CA configured, when at least one has.

    On a machine where nothing is customised this is empty and uninteresting.
    Where some runtime has been pointed at a corporate CA, the ones that have
    not are the ones about to fail, and they are the finding.
    """
    configured = {store.ecosystem for store in detect_trust_stores(env)}
    if not configured:
        return []
    return sorted(set(CA_BUNDLE_VARS) - configured)
