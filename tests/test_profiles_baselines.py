"""Wave-4 capability tests: profiles, maturity scoring, baselines."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from devrepro.project.profiles import detect_profile, score_maturity
from devrepro.snapshots.baseline import (
    diff_against_baseline,
    load_baseline,
    new_baseline,
    save_baseline,
)

if TYPE_CHECKING:
    from pathlib import Path


def _frontend_project(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "engines": {"node": ">=20"},
            }
        )
    )
    (tmp_path / "package-lock.json").write_text("{}")
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("on: push")
    return tmp_path


def test_detect_profile_frontend(tmp_path: Path) -> None:
    root = _frontend_project(tmp_path)
    report = detect_profile(root)
    assert report.profile == "frontend"
    assert report.confidence > 0
    assert any("frontend" in s for s in report.signals)


def test_detect_profile_unknown(tmp_path: Path) -> None:
    report = detect_profile(tmp_path)
    assert report.profile == "unknown"
    assert report.confidence == 0.0


def test_maturity_score_explainable(tmp_path: Path) -> None:
    root = _frontend_project(tmp_path)
    score = score_maturity(root)
    assert score.possible > 0
    # engines pinned + lockfile + CI => at least those factors earned
    by_name = {f.name: f for f in score.factors}
    assert by_name["runtime-pinned"].satisfied
    assert by_name["lockfile"].satisfied
    assert by_name["ci-declared"].satisfied
    text = score.explanation()
    assert "does not guarantee" in text  # honest disclaimer present
    assert "[PASS]" in text


def test_maturity_score_empty_repo_low(tmp_path: Path) -> None:
    score = score_maturity(tmp_path)
    assert score.total == 0
    assert score.percent == 0


# ---------- baselines ----------


def test_baseline_roundtrip_and_stable_id(tmp_path: Path) -> None:
    b = new_baseline("fp-123", {"node": ">=20"}, ("DATABASE_URL",), notes="team approved")
    path = save_baseline(b, tmp_path / "baseline.json")
    loaded = load_baseline(path)
    assert loaded.baseline_id == b.baseline_id
    assert loaded.tools == {"node": ">=20"}
    assert loaded.required_env_names == ("DATABASE_URL",)
    # deterministic id: same content, same id
    again = new_baseline("fp-123", {"node": ">=20"}, ("DATABASE_URL",))
    assert again.baseline_id == b.baseline_id


def test_baseline_rejects_unknown_schema(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": "9.9"}))
    try:
        load_baseline(p)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "unsupported baseline schema_version" in str(exc)


def test_diff_against_baseline_classifies_severity() -> None:
    b = new_baseline(
        "fp",
        {"node": ">=20 <22"},
        ("API_URL",),
        require_docker=True,
    )
    diff = diff_against_baseline(
        baseline=b,
        machine_tools={"node": "18.0.0"},
        machine_env_names=set(),
        docker_available=False,
        path_duplicates=3,
    )
    blockers = {e.name for e in diff.blockers}
    assert "node" in blockers
    assert "API_URL" in blockers
    assert "daemon" in blockers
    warns = {e.name for e in diff.warnings}
    assert "duplicates" in warns
    # every entry carries project-impact explanation
    assert all(e.project_impact for e in diff.entries)


def test_diff_against_baseline_all_ok() -> None:
    b = new_baseline("fp", {"node": ">=20"}, ("A_VAR",))
    diff = diff_against_baseline(
        baseline=b,
        machine_tools={"node": "22.1.0"},
        machine_env_names={"A_VAR"},
        docker_available=False,  # not required -> no entry
    )
    assert not diff.blockers
    assert not diff.warnings
