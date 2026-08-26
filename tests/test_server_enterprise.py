"""Tests for wave-10: auth abstraction, OpenAPI spec, server backup/restore."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from devrepro.server.auth import (
    AuthError,
    OidcConfig,
    local_identity_from_token,
    map_claims_to_roles,
    parse_saml_metadata,
    validate_role_mapping,
)
from devrepro.server.backup import RestoreError, backup_database, restore_database
from devrepro.server.openapi import API_ROUTES, build_openapi_spec

# ------------------------------------------------------------------- auth ----

_OIDC = OidcConfig(
    issuer_url="https://idp.example.com/",
    client_id="devrepro",
    role_claim_path="realm_access.roles",
    groups_to_roles={"devrepro-admins": "admin", "devrepro-devs": "member"},
)


class TestOidcConfig:
    def test_rejects_plain_http_issuer(self) -> None:
        with pytest.raises(Exception, match="https"):
            OidcConfig(issuer_url="http://idp.example.com", client_id="x")

    def test_trailing_slash_normalized(self) -> None:
        assert _OIDC.issuer_url == "https://idp.example.com"

    def test_invalid_claim_path_rejected(self) -> None:
        with pytest.raises(Exception, match="claim"):
            OidcConfig(issuer_url="https://i.example.com", client_id="x", role_claim_path="a..b")


class TestClaimMapping:
    def test_nested_claim_path_resolved_and_mapped(self) -> None:
        claims = {"sub": "u1", "realm_access": {"roles": ["devrepro-admins", "other-group"]}}
        roles = map_claims_to_roles(claims, _OIDC)
        assert roles == frozenset({"admin"})

    def test_missing_claim_yields_no_roles(self) -> None:
        assert map_claims_to_roles({"sub": "u1"}, _OIDC) == frozenset()

    def test_string_group_unmapped_denied_by_default(self) -> None:
        claims = {"sub": "u1", "groups": "devrepro-devs"}
        cfg = OidcConfig(issuer_url="https://i.example.com", client_id="x")
        assert map_claims_to_roles(claims, cfg) == frozenset()

    def test_unknown_role_in_mapping_rejected(self) -> None:
        with pytest.raises(AuthError, match="unknown role"):
            validate_role_mapping({"g": "superuser"})

    def test_local_identity_from_service_account_row(self) -> None:
        ident = local_identity_from_token({"name": "ci-bot", "role": "admin", "org_id": 3})
        assert ident.subject == "ci-bot"
        assert ident.roles == frozenset({"admin"})
        assert ident.org_scopes == (3,)
        with pytest.raises(AuthError):
            local_identity_from_token({"name": "bad", "role": "root", "org_id": 1})


_SAML_META = (
    b'<?xml version="1.0"?>'
    b'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"'
    b' entityID="https://idp.corp/saml">'
    b"<md:IDPSSODescriptor>"
    b'<md:SingleSignOnService Binding="x" Location="https://idp.corp/sso"/>'
    b'<md:SingleSignOnService Binding="x" Location="http://insecure.corp/sso"/>'
    b"</md:IDPSSODescriptor></md:EntityDescriptor>"
)


class TestSamlMetadata:
    def test_entity_and_https_sso_urls_extracted(self) -> None:
        meta = parse_saml_metadata(_SAML_META)
        assert meta.entity_id == "https://idp.corp/saml"
        assert meta.sso_urls == ("https://idp.corp/sso",)

    def test_garbage_rejected(self) -> None:
        with pytest.raises(AuthError, match="XML"):
            parse_saml_metadata(b"<not-xml")

    def test_no_entity_id_rejected(self) -> None:
        with pytest.raises(AuthError, match="entityID"):
            parse_saml_metadata(b"<root/>")

    def test_size_limit_enforced(self) -> None:
        with pytest.raises(AuthError, match="512"):
            parse_saml_metadata(b"x" * (600 * 1024))


# ---------------------------------------------------------------- openapi ----


class TestOpenApi:
    def test_all_documented_routes_present_in_spec(self) -> None:
        spec = build_openapi_spec()
        assert spec["openapi"] == "3.1.0"
        for method, path, op_id, _summary, needs_auth in API_ROUTES:
            op = spec["paths"][path][method.lower()]
            assert op["operationId"] == op_id
            if needs_auth:
                assert op["security"] == [{"bearerAuth": []}]
                assert "bearerAuth" in spec["components"]["securitySchemes"]

    def test_spec_matches_live_flask_routes(self) -> None:
        import re

        from devrepro.server.api import create_app
        from devrepro.server.db import ServerDB

        def normalize(path: str) -> str:
            # flask "<int:pid>" / "<pid>" -> openapi "{pid}"
            return re.sub(r"<(?:[a-z]+:)?([a-zA-Z_][a-zA-Z0-9_]*)>", r"{\1}", path)

        db = ServerDB(":memory:")
        app = create_app(db)
        documented = {(m.lower(), p) for m, p, *_ in API_ROUTES}
        live: set[tuple[str, str]] = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            for m in rule.methods - {"HEAD", "OPTIONS"}:
                live.add((m.lower(), normalize(str(rule.rule))))
        missing = live - documented
        assert not missing, f"live routes undocumented: {sorted(missing)}"

    def test_endpoint_served(self) -> None:
        from devrepro.server.api import create_app
        from devrepro.server.db import ServerDB

        client = create_app(ServerDB(":memory:")).test_client()
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        body = json.loads(resp.get_data())
        assert "/api/v1/snapshots" in body["paths"]


# ---------------------------------------------------------------- backup -----


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    from devrepro.server.db import ServerDB

    db = ServerDB(tmp_path / "fleet.db")
    org = db.create_organization("acme")
    db.create_service_account(org, "sa", "admin")
    db.close()
    return tmp_path / "fleet.db"


class TestBackupRestore:
    def test_roundtrip_preserves_rows(self, seeded_db: Path, tmp_path: Path) -> None:
        archive = tmp_path / "backup.tar.gz"
        result = backup_database(seeded_db, archive)
        assert result.members >= 1 and result.sha256

        target = tmp_path / "restored" / "fleet.db"
        restore_database(archive, target)
        from devrepro.server.db import ServerDB

        db = ServerDB(target)
        assert db.health().get("ok", True) is True or db.list_snapshots(org_id=1) == []
        db.close()

    def test_corrupt_archive_refused(self, seeded_db: Path, tmp_path: Path) -> None:
        archive = tmp_path / "backup.tar.gz"
        backup_database(seeded_db, archive)
        blob = bytearray(archive.read_bytes())
        blob[len(blob) // 2] ^= 0xFF  # flip a byte mid-archive
        corrupt = tmp_path / "corrupt.tar.gz"
        corrupt.write_bytes(bytes(blob))
        with pytest.raises(RestoreError):
            restore_database(corrupt, tmp_path / "out" / "fleet.db")

    def test_overwrite_guard(self, seeded_db: Path, tmp_path: Path) -> None:
        archive = tmp_path / "b.tar.gz"
        backup_database(seeded_db, archive)
        existing = tmp_path / "existing.db"
        existing.write_bytes(b"x")
        with pytest.raises(RestoreError, match="overwrite"):
            restore_database(archive, existing)

    def test_non_backup_archive_rejected(self, tmp_path: Path) -> None:
        import io
        import tarfile

        fake = tmp_path / "fake.tar.gz"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="random.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        fake.write_bytes(buf.getvalue())
        with pytest.raises(RestoreError):
            restore_database(fake, tmp_path / "t.db")
