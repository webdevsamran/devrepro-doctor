"""The ways a working tree is incomplete, and git tells you nothing.

Each case here is one that produces a build failure naming something other than
the cause: LFS pointer files that look like corrupt binaries, a sparse checkout
whose missing directory leaves `git status` clean, a shallow clone that breaks
`git describe`, and a credential helper that is configured but absent, which in
CI is a hang and then a timeout.

`git_health` took no runner and built its own, so every branch below was
reachable only on a machine that happened to be in the right state. It takes
one now, and these drive it from recorded output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.core.models import FindingState, PlatformInfo
from devrepro.core.runner import CommandResult
from devrepro.git.health import BUNDLED_CREDENTIAL_HELPERS, git_health
from devrepro.probes.base import ProbeContext
from devrepro.probes.git_checkout import GitCheckoutProbe

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

NL = chr(10)


class GitRunner:
    """Answers `git` by matching a distinctive token in the argv.

    `RecordingRunner` keys on `argv[0]` and pops a queue in order, and this
    probe issues a dozen different `git` subcommands -- so a queue would
    silently mis-associate answers the moment the probe reordered a call.
    """

    def __init__(self, table: dict[str, str]) -> None:
        self.table = table
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        joined = " ".join(argv)
        for token, stdout in self.table.items():
            if token in joined:
                return CommandResult(argv, 0, stdout, "")
        return CommandResult(argv, 1, "", "")


def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main" + NL, encoding="utf-8")
    return tmp_path


def probe(root: Path, runner: GitRunner) -> GitCheckoutProbe:
    ctx = ProbeContext(
        runner=runner,
        platform="linux",
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        project_dir=root,
        env={"PATH": "/usr/bin"},
    )
    return GitCheckoutProbe(ctx)


def ids(root: Path, runner: GitRunner) -> list[str]:
    return [f.rule_id for f in probe(root, runner).run().findings]


# ------------------------------------------------------------------- LFS


def test_lfs_tracked_paths_with_no_lfs_installed_is_a_blocker(tmp_path: Path) -> None:
    """The failure that looks like a corrupt binary rather than a missing tool."""
    root = repo(tmp_path)
    (root / ".gitattributes").write_text("*.psd filter=lfs diff=lfs merge=lfs -text" + NL)

    findings = probe(root, GitRunner({})).run().findings
    match = next(f for f in findings if f.rule_id == "git/lfs-required-not-installed")

    assert match.state is FindingState.BLOCKED
    assert "pointer files" in (match.remediation_hint or "")


def test_lfs_installed_but_not_initialised_is_its_own_state(tmp_path: Path) -> None:
    """Installed and initialised have the same symptom and different fixes."""
    root = repo(tmp_path)
    (root / ".gitattributes").write_text("*.bin filter=lfs" + NL)
    runner = GitRunner({"lfs version": "git-lfs/3.5.1"})

    assert "git/lfs-not-initialised" in ids(root, runner)


def test_lfs_ready_is_recorded_as_a_pass(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".gitattributes").write_text("*.bin filter=lfs" + NL)
    runner = GitRunner(
        {"lfs version": "git-lfs/3.5.1", "--get filter.lfs.smudge": "git-lfs smudge -- %f"}
    )

    assert "git/lfs-ready" in ids(root, runner)


def test_a_repository_without_lfs_paths_says_nothing_about_lfs(tmp_path: Path) -> None:
    """Most repositories do not use LFS; none of them should hear about it."""
    root = repo(tmp_path)
    assert [i for i in ids(root, GitRunner({})) if "lfs" in i] == []


def test_lfs_declared_in_a_nested_gitattributes_still_counts(tmp_path: Path) -> None:
    """A monorepo keeps `.gitattributes` beside each package."""
    root = repo(tmp_path)
    nested = root / "packages" / "assets"
    nested.mkdir(parents=True)
    (nested / ".gitattributes").write_text("*.mp4 filter=lfs" + NL)

    assert git_health(root, runner=GitRunner({})).lfs_required is True


# --------------------------------------------------------- incompleteness


def test_an_uninitialised_submodule_is_reported(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".gitmodules").write_text(
        '[submodule "vendor/lib"]' + NL + "  path = vendor/lib" + NL + "  url = https://x/y" + NL,
        encoding="utf-8",
    )

    findings = probe(root, GitRunner({})).run().findings
    match = next(f for f in findings if f.rule_id == "git/submodules-uninitialised")

    assert match.state is FindingState.ERROR
    assert "vendor/lib" in match.summary + (match.detected or "")


def test_a_sparse_checkout_is_reported_with_its_pattern_count(tmp_path: Path) -> None:
    root = repo(tmp_path)
    info = root / ".git" / "info"
    info.mkdir()
    (info / "sparse-checkout").write_text("/*" + NL + "!/docs/" + NL + "# comment" + NL)
    runner = GitRunner({"--get core.sparseCheckout": "true"})

    findings = probe(root, runner).run().findings
    match = next(f for f in findings if f.rule_id == "git/sparse-checkout-active")

    assert "2 pattern(s)" in match.summary
    assert match.state is FindingState.INFO


def test_a_shallow_clone_is_a_warning(tmp_path: Path) -> None:
    root = repo(tmp_path)
    runner = GitRunner({"--is-shallow-repository": "true"})

    findings = probe(root, runner).run().findings
    match = next(f for f in findings if f.rule_id == "git/shallow-clone")

    assert match.state is FindingState.WARN
    assert "describe" in (match.remediation_hint or "")


def test_a_partial_clone_names_its_filter(tmp_path: Path) -> None:
    root = repo(tmp_path)
    runner = GitRunner({"remote.origin.partialclonefilter": "blob:none"})

    findings = probe(root, runner).run().findings
    match = next(f for f in findings if f.rule_id == "git/partial-clone")

    assert match.detected == "blob:none"


def test_a_complete_checkout_reports_nothing(tmp_path: Path) -> None:
    assert ids(repo(tmp_path), GitRunner({})) == []


def test_a_directory_that_is_not_a_repository_is_not_an_error(tmp_path: Path) -> None:
    result = probe(tmp_path, GitRunner({})).run()
    assert result.findings == ()
    assert result.data == {"is_repo": False}


# ------------------------------------------------------------ credentials


def test_a_configured_helper_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    """In CI this is a hang and a timeout, with nothing naming the helper."""
    root = repo(tmp_path)
    runner = GitRunner({"--global --get-all credential.helper": "no-such-helper"})

    findings = probe(root, runner).run().findings
    match = next(f for f in findings if f.rule_id == "git/credential-helper-missing")

    assert match.state is FindingState.WARN
    assert "no-such-helper" in match.summary
    assert "global" in match.summary


@pytest.mark.parametrize("name", sorted(BUNDLED_CREDENTIAL_HELPERS))
def test_helpers_git_ships_are_not_reported_missing(tmp_path: Path, name: str) -> None:
    """These live in git's exec directory, not on PATH."""
    root = repo(tmp_path)
    runner = GitRunner({"--global --get-all credential.helper": name})
    assert "git/credential-helper-missing" not in ids(root, runner)


def test_the_store_helper_is_flagged_as_plaintext(tmp_path: Path) -> None:
    root = repo(tmp_path)
    runner = GitRunner({"--global --get-all credential.helper": "store"})

    findings = probe(root, runner).run().findings
    match = next(f for f in findings if f.rule_id == "git/credential-store-plaintext")

    assert match.state is FindingState.INFO
    assert "never reads the file" in (match.remediation_hint or "")


def test_a_shell_fragment_helper_is_recorded_as_custom_not_verbatim(tmp_path: Path) -> None:
    """The fragment is the user's text and may name internal hosts or paths."""
    root = repo(tmp_path)
    fragment = "!f() { echo password=$INTERNAL_TOKEN; }; f"
    runner = GitRunner({"--local --get-all credential.helper": fragment})

    helpers = git_health(root, runner=runner).credential_helpers

    assert [h.name for h in helpers] == ["custom"]
    assert all("INTERNAL_TOKEN" not in h.name for h in helpers)


def test_no_helper_value_ever_reaches_the_probe_data(tmp_path: Path) -> None:
    """The credential-safety claim, checked against what a report would carry."""
    root = repo(tmp_path)
    runner = GitRunner(
        {"--global --get-all credential.helper": "manager --secret hunter2-do-not-leak"}
    )

    serialized = repr(probe(root, runner).run().data)

    assert "hunter2-do-not-leak" not in serialized
    assert "manager" in serialized


def test_helpers_are_read_from_every_scope(tmp_path: Path) -> None:
    root = repo(tmp_path)
    runner = GitRunner(
        {
            "--local --get-all credential.helper": "store",
            "--system --get-all credential.helper": "manager",
        }
    )

    helpers = git_health(root, runner=runner).credential_helpers

    assert {(h.name, h.scope) for h in helpers} == {("store", "local"), ("manager", "system")}


def test_show_origin_is_never_used(tmp_path: Path) -> None:
    """It would name the user's global config path, which contains their name.

    Asking each scope separately costs two more subprocess calls and keeps
    identity out of the report entirely.
    """
    root = repo(tmp_path)
    runner = GitRunner({})
    git_health(root, runner=runner)

    assert not any("--show-origin" in " ".join(call) for call in runner.calls)


def test_the_probe_never_runs_a_credential_helper(tmp_path: Path) -> None:
    """Several block on stdin; a diagnostic that hangs is worse than a silent one."""
    root = repo(tmp_path)
    runner = GitRunner({"--global --get-all credential.helper": "manager"})
    probe(root, runner).run()

    for call in runner.calls:
        joined = " ".join(call)
        assert "credential-manager" not in joined
        assert not (len(call) > 1 and call[1] == "credential")


def test_every_finding_carries_evidence_and_a_remediation(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".gitattributes").write_text("*.bin filter=lfs" + NL)
    (root / ".gitmodules").write_text(
        '[submodule "a"]' + NL + "  path = a" + NL + "  url = https://x" + NL, encoding="utf-8"
    )
    runner = GitRunner(
        {
            "--is-shallow-repository": "true",
            "--global --get-all credential.helper": "store",
        }
    )

    findings = probe(root, runner).run().findings

    assert len(findings) >= 4
    for finding in findings:
        assert finding.evidence, finding.rule_id
        assert finding.component == "git", finding.rule_id
        if finding.state is not FindingState.PASS:
            assert finding.remediation_hint, finding.rule_id
