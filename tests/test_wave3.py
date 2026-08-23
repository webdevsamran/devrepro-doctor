"""Wave-3 capability tests: envvars, ports, git health, network, windows, wsl."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from devrepro.envvars.analysis import (
    dotenv_safety_scan,
    trace_env_origins,
    verify_env_policy,
)
from devrepro.git.health import git_health
from devrepro.network.diagnostics import (
    _strip_credentials,
    check_clock,
    collect_proxy_settings,
)
from devrepro.platforms.wsl_probe import (
    detect_path_contamination,
    filesystem_location_guidance,
)
from devrepro.services.ports import (
    collect_port_declarations,
    infer_required_services,
)

NL = chr(10)

GITIGNORE_ENV = """.env
"""

ENV_TWO_VARS = """DATABASE_URL=postgres://localhost/db
API_TOKEN=ignored-value
"""

ENV_ONE_VAR = """DATABASE_URL=
"""

COMPOSE_MULTI = """services:
  db:
    image: postgres:16
    ports:
      - "5432:5432"
  web:
    ports:
      - 3000
"""

COMPOSE_DB = """services:
  db:
    ports:
      - 5432
"""


# ---------- envvar tracing / policy / dotenv safety ----------


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text(GITIGNORE_ENV)
    (tmp_path / ".env").write_text(ENV_TWO_VARS)
    (tmp_path / ".env.example").write_text(ENV_ONE_VAR)
    return tmp_path


def test_trace_env_origins_names_only(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    origins = trace_env_origins(root)
    names = {o.name for o in origins}
    assert {"DATABASE_URL", "API_TOKEN"} <= names
    # values must never be recorded anywhere in the origin data
    blob = repr(origins)
    assert "postgres://" not in blob
    assert "ignored-value" not in blob


def test_env_policy_missing_and_duplicates(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    report = verify_env_policy(root, required=("MISSING_VAR",), forbidden=("API_TOKEN",))
    assert report.missing_required == ("MISSING_VAR",)
    assert report.forbidden_present == ("API_TOKEN",)
    assert not report.ok


def test_dotenv_safety_flags_untracked_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PASSWORD=hunter2" + NL)
    findings = dotenv_safety_scan(tmp_path)
    crit = [f for f in findings if f.severity == "critical"]
    assert crit, "untracked .env with secret-looking name must be critical"
    blob = repr(findings)
    assert "hunter2" not in blob  # value never recorded


def test_dotenv_safety_detects_credential_shapes(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(GITIGNORE_ENV)
    fake_pat = "ghp_" + "a" * 30  # synthetic fixture, not a real token
    (tmp_path / ".env").write_text(f"GITHUB_TOKEN={fake_pat}" + NL)
    findings = dotenv_safety_scan(tmp_path)
    assert any("credential formats" in f.detail for f in findings)
    assert all(fake_pat not in f.detail for f in findings)


# ---------- ports & services ----------


def test_collect_ports_from_compose_and_devcontainer(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_MULTI)
    dc = tmp_path / ".devcontainer"
    dc.mkdir()
    (dc / "devcontainer.json").write_text('{"forwardPorts": [8080, "9090:9090"]}')
    decls = collect_port_declarations(tmp_path)
    ports = {d.port for d in decls}
    assert {5432, 3000, 8080, 9090} <= ports
    svc = {d.service for d in decls if d.port == 5432}
    assert svc == {"db"}


def test_port_conflict_detection() -> None:
    from devrepro.services.ports import PortDeclaration, check_port_conflicts

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    busy_port = s.getsockname()[1]
    s.listen(1)
    try:
        statuses = check_port_conflicts(
            (
                PortDeclaration(busy_port, "test"),
                PortDeclaration(0, "skip-invalid"),
            )
        )
    finally:
        s.close()
    by_port = {st.port: st for st in statuses}
    assert by_port[busy_port].free is False


def test_infer_required_services(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text(COMPOSE_DB)
    inferred = infer_required_services(tmp_path)
    assert "postgres" in inferred


# ---------- git health ----------


def test_git_health_on_real_repo() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report = git_health(repo_root)
    assert report.is_repo
    # this repo has no .gitmodules; submodule list must be empty, not crash
    assert report.submodules == ()
    # credential helper must never leak a stored value
    assert report.credential_helper_name is None or "@" not in str(report.credential_helper_name)


def test_git_health_non_repo(tmp_path: Path) -> None:
    report = git_health(tmp_path)
    assert not report.is_repo
    assert not report.signing_configured


# ---------- network (offline parts only; network checks are opt-in) ----------


def test_strip_credentials() -> None:
    assert _strip_credentials("https://user:secret@proxy.example.com:8080") == (
        "https://***@proxy.example.com:8080"
    )


def test_proxy_report_redacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "https://alice:hunter2@corp-proxy:3128")
    report = collect_proxy_settings()
    val = report.env_proxies.get("HTTPS_PROXY", "")
    assert "alice" not in val and "hunter2" not in val
    assert "***" in val


def test_clock_offline_plausible() -> None:
    cc = check_clock(allow_network=False)
    assert cc.plausible
    assert cc.skew_seconds is None


# ---------- WSL helpers (pure logic, no wsl.exe needed) ----------


def test_wsl_path_contamination_detection() -> None:
    entries = [
        "/usr/local/bin",
        "/mnt/c/Program Files/Python312",
        "/mnt/c/Users/me/AppData/Local/Microsoft/WindowsApps",
    ]
    contaminated = detect_path_contamination(entries)
    assert len(contaminated) == 2
    assert "/usr/local/bin" not in contaminated


def test_wsl_fs_location_guidance() -> None:
    warn = filesystem_location_guidance("/mnt/c/projects/web")
    assert warn["severity"] == "warn"
    ok = filesystem_location_guidance("/home/dev/app")
    assert ok["severity"] == "ok"


# ---------- windows probes (platform-guarded) ----------


@pytest.mark.skipif(os.name != "nt", reason="Windows-only")
def test_windows_probes_run_on_windows() -> None:
    from devrepro.platforms.windows_extra import (
        check_app_execution_aliases,
        check_long_paths,
    )

    alias = check_app_execution_aliases()
    assert isinstance(alias.python_alias_present, bool)
    lp = check_long_paths()
    assert lp.long_paths_enabled in (True, False, None)
