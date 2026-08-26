"""Tests for wave-1 capabilities: monorepo intel, CI parsers, protocol v2,
drift timeline, remediation graph, generators."""

from __future__ import annotations

import json

import pytest
from devrepro.core.models import RiskLevel
from devrepro.drift.timeline import build_timeline, root_cause_hints
from devrepro.generators import (
    generate_devcontainer,
    generate_devrepro_toml,
    generate_tool_versions,
    write_generated,
)
from devrepro.project.ci_parsers import (
    CiToolchain,
    collect_ci_toolchains,
    local_vs_ci_diff,
)
from devrepro.project.monorepo import analyze_monorepo
from devrepro.remediation.graph import (
    DryRunTransaction,
    PlanCycleError,
    RemediationStep,
    build_execution_order,
)
from devrepro.snapshots.protocol import (
    FIELD_CLASSES,
    FieldClass,
    classify_payload,
    migrate_snapshot,
    project_fingerprint,
)

# ---------- monorepo ----------


def _make_repo(tmp_path, *, engines_node=">=20", child_engines=None):
    root_pkg = {
        "name": "root",
        "workspaces": ["apps/*"],
        "engines": {"node": engines_node},
    }
    (tmp_path / "package.json").write_text(json.dumps(root_pkg))
    app = tmp_path / "apps" / "web"
    app.mkdir(parents=True)
    child = {"name": "web"}
    if child_engines:
        child["engines"] = {"node": child_engines}
    (app / "package.json").write_text(json.dumps(child))
    (app / "src.ts").write_text("export const x = 1;" + chr(10))
    return tmp_path


def test_monorepo_detects_workspace_and_projects(tmp_path):
    repo = _make_repo(tmp_path)
    report = analyze_monorepo(repo)
    assert report.is_monorepo
    assert any("workspaces" in m for m in report.workspace_markers)
    paths = {p.path for p in report.projects}
    assert "." in paths and "apps/web" in paths


def test_nested_conflict_detected(tmp_path):
    repo = _make_repo(tmp_path, engines_node=">=20", child_engines="<16")
    report = analyze_monorepo(repo)
    assert len(report.conflicts) == 1
    c = report.conflicts[0]
    assert c.tool == "node" and c.parent_spec == ">=20" and c.child_spec == "<16"


def test_no_conflict_when_compatible(tmp_path):
    repo = _make_repo(tmp_path, engines_node=">=18", child_engines=">=20")
    assert analyze_monorepo(repo).conflicts == ()


def test_language_inventory_and_lockfiles(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "package-lock.json").write_text("{}")
    report = analyze_monorepo(repo)
    assert report.inventory.primary() in ("typescript", "javascript")
    assert "node" in report.lockfiles.covered


# ---------- CI parsers ----------

GHA_WORKFLOW = """\
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: 20
"""


def test_github_actions_parser(tmp_path):
    wf = tmp_path / ".github" / "workflows" / "ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text(GHA_WORKFLOW)
    tools = collect_ci_toolchains(tmp_path)
    by = {t.tool: t.spec for t in tools}
    assert by.get("python") == "3.12"
    assert by.get("node") == "20"


def test_gitlab_ci_image_parser(tmp_path):
    gl = tmp_path / ".gitlab-ci.yml"
    gl.write_text("image: python:3.12-bookworm" + chr(10))
    by = {t.tool: t.spec for t in collect_ci_toolchains(tmp_path)}
    assert by.get("python") == "3.12-bookworm"


def test_local_vs_ci_diff_mismatch():
    ci = (CiToolchain("python", "3.12", ".github/workflows/ci.yml"),)
    rows = local_vs_ci_diff(ci, {"python": "3.10"})
    assert rows[0]["status"] == "mismatch"
    assert "explains" in rows[0]["detail"]


def test_local_vs_ci_diff_match():
    ci = (CiToolchain("python", ">=3.11", "ci.yml"),)
    rows = local_vs_ci_diff(ci, {"python": "3.12.4"})
    assert rows[0]["status"] == "match"


def test_local_vs_ci_diff_wildcard_and_absent():
    ci = (CiToolchain("node", "*", "ci.yml"),)
    rows = local_vs_ci_diff(ci, {"node": "18", "python": "3.12"})
    statuses = {r["tool"]: r["status"] for r in rows}
    assert statuses["node"] == "wildcard"
    assert statuses["python"] == "ci-absent"


# ---------- protocol v2 ----------


def test_field_classification_covers_forbidden():
    assert FIELD_CLASSES["tokens"] is FieldClass.SECRET_FORBIDDEN
    payload = {"schema_version": "2.0", "tools": [], "tokens": ["x"]}
    classes = classify_payload(payload)
    assert classes["tools"] == "machine-sensitive"
    assert classes["tokens"] == "secret-forbidden"


def test_v1_migration_adds_provenance_and_fingerprint():
    v1 = {
        "schema_version": "1.0",
        "devrepro_version": "0.1.0",
        "requirements_fingerprint": [
            {"ecosystem": "node", "name": "node", "spec": ">=20"},
        ],
    }
    v2 = migrate_snapshot(v1)
    assert v2["protocol_version"].startswith("2.")
    assert v2["provenance"]["producer"] == "devrepro-doctor"
    assert len(v2["project_fingerprint"]) == 16


def test_migration_rejects_unknown_future_version():
    with pytest.raises(ValueError, match="unsupported"):
        migrate_snapshot({"schema_version": "9.9"})


def test_project_fingerprint_deterministic_and_order_insensitive():
    a = [
        {"ecosystem": "node", "name": "node", "spec": ">=20"},
        {"ecosystem": "python", "name": "python", "spec": ">=3.11"},
    ]
    b = list(reversed(a))
    assert project_fingerprint(a) == project_fingerprint(b)


# ---------- drift timeline ----------


def test_timeline_and_root_cause():
    snaps = [
        {
            "snapshot_id": "aaa",
            "tools": [{"name": "node", "version": "18.0.0"}],
            "containers": {"docker_daemon_ok": True},
        },
        {
            "snapshot_id": "bbb",
            "tools": [{"name": "node", "version": "20.1.0"}],
            "containers": {"docker_daemon_ok": False},
        },
    ]
    tl = build_timeline(snaps)
    kinds = {(e.component, e.name, e.kind) for e in tl.events}
    assert ("tool", "node", "version-changed") in kinds
    assert ("container", "docker-daemon", "state-changed") in kinds
    hints = root_cause_hints(tl, "container", "docker-daemon")
    assert hints and hints[0].before == "ok" and hints[0].after == "down"


# ---------- remediation graph ----------


def _steps():
    return (
        RemediationStep(
            "install-node",
            "Install Node 20",
            RiskLevel.MEDIUM,
            commands=("nvm install 20",),
            post_checks=("node --version",),
        ),
        RemediationStep("clear-cache", "Clear npm cache", RiskLevel.SAFE),
        RemediationStep(
            "rebuild",
            "Rebuild deps",
            RiskLevel.LOW,
            prerequisites=("install-node", "clear-cache"),
        ),
    )


def test_execution_order_respects_prerequisites():
    order = [s.id for s in build_execution_order(_steps())]
    assert order.index("rebuild") > order.index("install-node")
    assert order.index("rebuild") > order.index("clear-cache")


def test_cycle_detection():
    bad = (
        RemediationStep("a", "A", RiskLevel.SAFE, prerequisites=("b",)),
        RemediationStep("b", "B", RiskLevel.SAFE, prerequisites=("a",)),
    )
    with pytest.raises(PlanCycleError, match="cycle"):
        build_execution_order(bad)


def test_unknown_prerequisite_rejected():
    with pytest.raises(PlanCycleError, match="unknown"):
        build_execution_order((RemediationStep("a", "A", RiskLevel.SAFE, prerequisites=("zzz",)),))


def test_dry_run_requires_confirmation_for_medium_risk():
    tx = DryRunTransaction(steps=_steps())
    result = tx.run()
    assert "clear-cache" in result["executed"]
    assert "install-node" not in result["executed"]
    skipped_reasons = dict(result["skipped"])
    assert "explicit confirmation" in skipped_reasons["install-node"]
    tx2 = DryRunTransaction(steps=_steps(), confirmed_ids=frozenset({"install-node"}))
    r2 = tx2.run()
    assert set(r2["executed"]) == {"install-node", "clear-cache", "rebuild"}


# ---------- generators ----------


def test_devrepro_toml_draft_contains_requirements():
    out = generate_devrepro_toml(
        {"python": ">=3.11", "git": "*"}, required_env_names=("DATABASE_URL",)
    )
    assert "[required_runtimes]" in out
    assert 'python = ">=3.11"' in out
    assert '"DATABASE_URL"' in out


def test_write_generated_never_overwrites_without_approval(tmp_path):
    target = tmp_path / ".devrepro.toml"
    target.write_text("[supported_os]" + chr(10) + "windows = true" + chr(10))
    gen = write_generated(target, generate_devrepro_toml({"python": ">=3.11"}))
    assert gen.requires_review and gen.diff
    assert "REVIEW BEFORE COMMITTING" not in target.read_text()
    write_generated(target, generate_devrepro_toml({"python": ">=3.11"}), allow_overwrite=True)
    assert "python" in target.read_text()


def test_tool_versions_styles():
    mise = generate_tool_versions({"node": "^20.0.0"}, style="mise")
    asdf = generate_tool_versions({"node": "^20.0.0"}, style="asdf")
    assert "[tools]" in mise and 'node = "20.0.0"' in mise
    assert asdf.strip() == "node 20.0.0"
    assert "does NOT guarantee full reproducibility" in mise


def test_devcontainer_marked_generated():
    dc = json.loads(generate_devcontainer(forward_ports=(5432,)))
    assert "REVIEW REQUIRED" in dc["//"]
    assert dc["forwardPorts"] == [5432]
