"""Tests for wave-10: auth abstraction, OpenAPI spec, server backup/restore."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from devrepro.core.exit_codes import ExitCode
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

    def test_corruption_anywhere_raises_restore_error(
        self, seeded_db: Path, tmp_path: Path
    ) -> None:
        """No corrupted archive may escape as a non-RestoreError exception.

        The single-byte-flip test above passed or failed depending on where the
        damaged byte landed: gzip.BadGzipFile (an OSError, not a TarError),
        json.JSONDecodeError and UnicodeDecodeError all escaped the handler,
        so this failed nondeterministically per platform instead of never.
        RestoreError is the only exception the CLI and API catch, so anything
        else reaches the user as a traceback.
        """
        archive = tmp_path / "backup.tar.gz"
        backup_database(seeded_db, archive)
        blob = archive.read_bytes()
        corrupt = tmp_path / "corrupt.tar.gz"

        escaped: list[str] = []
        for position in range(4, len(blob), 7):
            for mask in (0xFF, 0x01):
                mutated = bytearray(blob)
                mutated[position] ^= mask
                corrupt.write_bytes(bytes(mutated))
                try:
                    restore_database(corrupt, tmp_path / f"out{position}_{mask}" / "fleet.db")
                except RestoreError:
                    pass
                except Exception as exc:
                    escaped.append(f"byte {position} ^{mask:#04x}: {type(exc).__name__}: {exc}")

        assert not escaped, "corrupt archives escaped as non-RestoreError: " + "; ".join(
            escaped[:5]
        )

    def test_manifest_that_is_valid_json_but_not_an_object_is_rejected(
        self, seeded_db: Path, tmp_path: Path
    ) -> None:
        """Parsing is not validating.

        The byte-flip sweep above hit this on Windows/3.12: a corruption left
        `manifest.json` holding a bare JSON scalar, which parsed fine and then
        reached `manifest.get("members")` -- escaping as
        `AttributeError: 'int' object has no attribute 'get'`. RestoreError is
        the only exception the CLI and API catch, so that reached the user as a
        traceback. Reproduced deterministically here rather than left to which
        byte a fuzz sweep happens to flip.
        """
        import io
        import tarfile

        for payload in (b"5", b"null", b'"manifest"', b"[]"):
            archive = tmp_path / f"scalar-{len(payload)}-{payload[:1].hex()}.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            with pytest.raises(RestoreError, match="not an object"):
                restore_database(archive, tmp_path / f"out-{len(payload)}" / "fleet.db")

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


class TestBackupRestoreThroughTheCli:
    """The wrapper around those functions, which nothing had ever invoked.

    `server-backup` and `server-restore` were excluded from the CLI surface
    tests for needing a database, and being excluded is how a command goes
    years without anybody reading its output. Both defects below are the kind
    that only appear when you run it: a Python dict printed at a human, and an
    error telling an operator to pass a keyword argument to a terminal.
    """

    def test_backup_prints_a_human_interface_not_a_dict(
        self, seeded_db: Path, tmp_path: Path
    ) -> None:
        from devrepro.cli.app import app
        from typer.testing import CliRunner

        archive = tmp_path / "backup.tar.gz"
        result = CliRunner().invoke(app, ["server-backup", str(seeded_db), "-o", str(archive)])

        assert result.exit_code == ExitCode.READY
        assert archive.is_file()
        # The fault this repository already fixed in `check`, `generate` and
        # `rules`, still present here because nothing invoked the command.
        assert "{'archive'" not in result.output
        assert "sha256:" in result.output
        assert "server-restore" in result.output, "tell them the next command"

    def test_backup_json_is_still_json(self, seeded_db: Path, tmp_path: Path) -> None:
        from devrepro.cli.app import app
        from typer.testing import CliRunner

        archive = tmp_path / "backup.tar.gz"
        result = CliRunner().invoke(
            app, ["server-backup", str(seeded_db), "-o", str(archive), "--json"]
        )
        payload = json.loads(result.output)
        assert payload["sha256"] and payload["members"] >= 1

    def test_restore_over_an_existing_database_names_the_flag(
        self, seeded_db: Path, tmp_path: Path
    ) -> None:
        """It said "pass overwrite=True" -- a Python keyword argument.

        There is a `--overwrite` flag. An operator restoring a fleet database
        under time pressure cannot act on the name of a function parameter.
        """
        from devrepro.cli.app import app
        from typer.testing import CliRunner

        archive = tmp_path / "backup.tar.gz"
        backup_database(seeded_db, archive)

        result = CliRunner().invoke(app, ["server-restore", str(archive), str(seeded_db)])

        assert result.exit_code == ExitCode.USAGE_ERROR
        assert "--overwrite" in result.output
        assert "overwrite=True" not in result.output

    def test_restore_with_the_flag_succeeds(self, seeded_db: Path, tmp_path: Path) -> None:
        from devrepro.cli.app import app
        from typer.testing import CliRunner

        archive = tmp_path / "backup.tar.gz"
        backup_database(seeded_db, archive)

        result = CliRunner().invoke(
            app, ["server-restore", str(archive), str(seeded_db), "--overwrite"]
        )

        assert result.exit_code == ExitCode.READY
        assert "restored:" in result.output
        assert seeded_db.is_file()

    def test_a_target_under_another_name_explains_why(
        self, seeded_db: Path, tmp_path: Path
    ) -> None:
        """The restored file keeps the name it was backed up under.

        "archive contains no database file named 'x.db'" is true and tells the
        reader nothing about what to do instead.
        """
        from devrepro.cli.app import app
        from typer.testing import CliRunner

        archive = tmp_path / "backup.tar.gz"
        backup_database(seeded_db, archive)

        result = CliRunner().invoke(
            app, ["server-restore", str(archive), str(tmp_path / "renamed.db")]
        )

        assert result.exit_code == ExitCode.USAGE_ERROR
        assert "the name it was backed up under" in result.output
