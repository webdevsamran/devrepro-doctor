"""Authentication abstraction for self-hosted team mode.

Layers
------
- ``local``      : built-in service accounts (already enforced by ServerDB).
- ``oidc``       : standards-based OIDC/OAuth2 bearer identity. The token
                   *introspection* itself must be performed by an actual IdP;
                   this module owns configuration validation, claim->RBAC
                   role mapping and identity normalization so any conforming
                   provider can be plugged in.
- ``saml``       : IdP metadata parsing (entity ID, SSO binding) only.
                   Assertion signature verification MUST be delegated to a
                   dedicated SAML stack; DevRepro never treats unverified
                   assertions as authenticated.

External IdP validation status: BLOCKED (no test IdP available in CI).
Claim-mapping behaviour is fully covered by deterministic unit tests using
synthetic claim documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AUTH_METHODS",
    "AuthError",
    "AuthIdentity",
    "OidcConfig",
    "SamlMetadata",
    "local_identity_from_token",
    "map_claims_to_roles",
    "parse_saml_metadata",
    "validate_role_mapping",
]

AUTH_METHODS = ("local", "oidc", "saml")

# Roles understood by the RBAC layer (see server/fleet.py authorization).
KNOWN_ROLES = frozenset({"admin", "maintainer", "member", "viewer"})


class AuthError(Exception):
    """Raised for misconfiguration or malformed identities."""


class OidcConfig(BaseModel):
    """Validated OIDC provider configuration."""

    model_config = ConfigDict(frozen=True)

    issuer_url: str = Field(description="HTTPS issuer, e.g. https://idp.example.com")
    client_id: str = Field(min_length=1)
    role_claim_path: str = Field(
        default="groups",
        description="Dotted claim path carrying group/role info, e.g. 'realm_access.roles'",
    )
    groups_to_roles: dict[str, str] = Field(default_factory=dict)

    @field_validator("issuer_url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("issuer_url must be https:// (plain http is never accepted)")
        return v.rstrip("/")

    @field_validator("role_claim_path")
    @classmethod
    def _sane_claim(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*", v):
            raise ValueError("role_claim_path must be dot-separated identifier segments")
        return v


@dataclass(frozen=True)
class AuthIdentity:
    """Normalized authenticated principal handed to RBAC checks."""

    subject: str
    roles: frozenset[str]
    method: str  # local | oidc | saml
    org_scopes: tuple[int, ...] = ()
    display_name: str | None = None


def validate_role_mapping(mapping: Mapping[str, str]) -> dict[str, str]:
    """Validate that every mapped target role is one we enforce."""
    out: dict[str, str] = {}
    for group, role in mapping.items():
        if role not in KNOWN_ROLES:
            raise AuthError(f"unknown role '{role}' for group '{group}'")
        out[group] = role
    return out


def map_claims_to_roles(claims: Mapping[str, object], config: OidcConfig) -> frozenset[str]:
    """Extract the configured claim path and translate groups to RBAC roles.

    Unknown groups contribute nothing (deny-by-default). A missing or empty
    claim yields no roles rather than an error: identity without membership
    is valid but powerless.
    """
    node: object = dict(claims)
    for segment in config.role_claim_path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return frozenset()
        node = node[segment]
    if isinstance(node, list):
        groups = [str(g) for g in node]
    elif isinstance(node, str):
        groups = [node]
    else:
        return frozenset()
    mapping = validate_role_mapping(config.groups_to_roles)
    roles: set[str] = set()
    for group in groups:
        role = mapping.get(group)
        if role:
            roles.add(role)
    return frozenset(roles)


def local_identity_from_token(token_record: Mapping[str, object]) -> AuthIdentity:
    """Build an identity from an already-authenticated service-account row."""
    role = str(token_record.get("role", ""))
    if role not in KNOWN_ROLES:
        raise AuthError(f"service account carries unknown role '{role}'")
    subject = str(token_record.get("name", "unknown"))
    org_raw = token_record.get("org_id")
    orgs = (int(org_raw),) if isinstance(org_raw, int) else ()
    return AuthIdentity(subject=subject, roles=frozenset({role}), method="local", org_scopes=orgs)


@dataclass(frozen=True)
class SamlMetadata:
    """Facts extracted from an IdP's SAML metadata document."""

    entity_id: str
    sso_urls: tuple[str, ...]


_MAX_METADATA_BYTES = 512 * 1024


def parse_saml_metadata(xml_bytes: bytes) -> SamlMetadata:
    """Parse the minimum safe facts from SAML IdP metadata.

    This is configuration discovery only — it never authenticates anything
    and assertion verification stays delegated to a real SAML stack.
    """
    if len(xml_bytes) > _MAX_METADATA_BYTES:
        raise AuthError("metadata document exceeds 512 KiB safety limit")
    try:
        root = ElementTree.fromstring(xml_bytes)  # noqa: S314 - bounded, admin-supplied input
    except ElementTree.ParseError as exc:
        raise AuthError(f"invalid SAML metadata XML: {exc}") from exc
    entity_id = root.attrib.get("entityID", "")
    if not entity_id:
        for el in root.iter():
            if el.tag.endswith("EntityDescriptor") and el.attrib.get("entityID"):
                entity_id = el.attrib["entityID"]
                break
    if not entity_id:
        raise AuthError("metadata has no entityID")
    urls: list[str] = []
    for el in root.iter():
        if el.tag.endswith("SingleSignOnService"):
            location = el.attrib.get("Location", "")
            if location.startswith("https://"):
                urls.append(location)
    return SamlMetadata(entity_id=entity_id, sso_urls=tuple(urls))
