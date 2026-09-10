"""A recipe somebody else can run, and the four ways one is worth nothing.

The README opens by promising to answer "Docker works there but not here". A
diff tells a maintainer what is different; a reproduction tells them they are
looking at the right thing. The difference between those two is where all the
value and all the dishonesty live.

Four ways a reproduction fails to be one, and a test for each:

- **It does not pin.** `FROM python:3.12` reproduces a different thing next
  month, and nothing about the file says so.
- **It has no assertion.** A recipe that sets up an environment and stops is a
  Dockerfile. What makes it a reproduction is that fixing the cause makes it
  stop working.
- **It hides what it left out.** A recipe that fails because a database was
  empty costs a maintainer more time than no recipe, because they debug the
  failure they were handed.
- **It reproduces the wrong thing.** The most expensive failure, because it
  looks like a success.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 -- pytest resolves fixture annotations

import pytest
from devrepro.core.models import (
    ContainerState,
    GpuStack,
    PlatformInfo,
    ProjectRequirement,
    RequirementKind,
    ScanReport,
)
from devrepro.reproduce.adapters import ADAPTERS, render_adapter
from devrepro.reproduce.bisect import (
    Dimension,
    bisect_dimensions,
    minimise_dimensions,
)
from devrepro.reproduce.corpus import (
    MINIMUM_SAMPLE,
    OUTCOMES,
    Attempt,
    CorpusError,
    read_corpus,
    record_attempt,
    summarise,
)
from devrepro.reproduce.emit import (
    render_compose,
    render_devcontainer,
    render_dockerfile,
    render_nix_flake,
    render_repro_script,
)
from devrepro.reproduce.recipe import FALLBACK_IMAGE, build_reproduction

NL = chr(10)


def requirement(ecosystem: str, name: str, spec: str) -> ProjectRequirement:
    return ProjectRequirement(
        ecosystem=ecosystem,
        name=name,
        spec=spec,
        kind=RequirementKind.RUNTIME,
        source_file="pyproject.toml",
    )


def report(
    *,
    requirements: tuple[ProjectRequirement, ...] = (),
    os_name: str = "Linux",
    containers: ContainerState | None = None,
    gpu: GpuStack | None = None,
) -> ScanReport:
    return ScanReport(
        schema_version="1.0",
        devrepro_version="0.2.0",
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        platform=PlatformInfo(os_name=os_name, os_version="1", arch="x86_64"),
        requirements=requirements,
        containers=containers,
        gpu=gpu,
    )


# ============================================================== the recipe


def test_the_base_image_carries_the_declared_runtime() -> None:
    recipe = build_reproduction(report(requirements=(requirement("python", "python", ">=3.11"),)))
    assert recipe.base_image == "python:3.11-bookworm"


def test_a_range_with_no_concrete_version_falls_back() -> None:
    """`*` names no version, and inventing one puts words in the project's mouth."""
    recipe = build_reproduction(report(requirements=(requirement("python", "python", "*"),)))
    assert recipe.base_image == FALLBACK_IMAGE


def test_the_fallback_is_debian_not_alpine() -> None:
    """musl changes how native extensions build.

    A reproduction that fails differently from the original is worse than none,
    and Alpine is the most common way to get one by accident.
    """
    assert "debian" in FALLBACK_IMAGE
    assert "alpine" not in FALLBACK_IMAGE


def test_installs_use_the_locked_form() -> None:
    """`npm install` resolves fresh and reproduces a different dependency tree."""
    recipe = build_reproduction(
        report(requirements=(requirement("npm", "node", ">=20"),)),
        present_lockfiles=frozenset({"package-lock.json"}),
    )
    commands = [step.command for step in recipe.steps]
    assert "npm ci" in commands
    assert "npm install" not in commands


def test_an_install_is_only_added_when_its_lockfile_exists() -> None:
    """`npm ci` with no lockfile fails on line one and reproduces nothing."""
    recipe = build_reproduction(report(requirements=(requirement("npm", "node", ">=20"),)))
    assert all(step.command != "npm ci" for step in recipe.steps)


def test_a_stray_lockfile_does_not_add_a_foreign_install() -> None:
    """A yarn.lock in a subdirectory should not add yarn to a pnpm project."""
    recipe = build_reproduction(
        report(requirements=(requirement("pnpm", "node", ">=20"),)),
        present_lockfiles=frozenset({"yarn.lock", "pnpm-lock.yaml"}),
    )
    commands = [step.command for step in recipe.steps]
    assert any("pnpm" in c for c in commands)
    assert not any("yarn" in c for c in commands)


def test_a_recipe_with_no_install_step_says_so_loudly() -> None:
    """The most expensive wrong reproduction: it looks like a successful one.

    Without an install step the container has a runtime and none of the
    project's dependencies, so the failing command dies with 'not found' -- a
    different failure, reported as though it were the reported one.
    """
    recipe = build_reproduction(report(), failing_command="pytest -q")
    kinds = [p.kind for p in recipe.preconditions]
    assert "no-install-step" in kinds


def test_an_environment_without_a_failing_command_is_not_a_reproduction() -> None:
    assert build_reproduction(report()).reproduces is False
    assert build_reproduction(report(), failing_command="make test").reproduces is True


def test_a_container_engine_in_the_original_is_an_unmet_precondition() -> None:
    """A mounted socket is a privilege escalation, not a build step."""
    recipe = build_reproduction(
        report(containers=ContainerState(docker_cli_version="27", docker_daemon_ok=True))
    )
    detail = next(p.detail for p in recipe.preconditions if p.kind == "container-in-container")
    assert "privilege escalation" in detail


def test_a_gpu_in_the_original_is_an_unmet_precondition() -> None:
    recipe = build_reproduction(report(gpu=GpuStack(nvidia_driver="550.54")))
    assert any(p.kind == "gpu" for p in recipe.preconditions)


def test_a_non_linux_original_says_what_will_not_reproduce() -> None:
    recipe = build_reproduction(report(os_name="Windows"))
    detail = next(p.detail for p in recipe.preconditions if p.kind == "platform")
    assert "case sensitivity" in detail


# ================================================================ emission


def test_the_failing_command_is_a_cmd_not_a_run() -> None:
    """A RUN that fails aborts the build, which looks like a broken recipe."""
    recipe = build_reproduction(report(), failing_command="pytest -q")
    body = render_dockerfile(recipe)
    assert 'CMD ["sh", "-c", "pytest -q"]' in body
    assert "RUN pytest -q" not in body


def test_an_unpinned_recipe_admits_it_in_its_own_header() -> None:
    """The file outlives the conversation about it."""
    body = render_dockerfile(build_reproduction(report()))
    assert "NOT PINNED" in body
    assert "mutable tag" in body


def test_a_pinned_recipe_does_not_carry_the_warning() -> None:
    import dataclasses

    recipe = dataclasses.replace(build_reproduction(report()), base_digest="debian@sha256:abc")
    body = render_dockerfile(recipe)
    assert "NOT PINNED" not in body
    assert "debian@sha256:abc" in body


def test_every_emitted_file_says_where_it_came_from() -> None:
    """The likeliest fate of a generated file is being found later and followed."""
    recipe = build_reproduction(report(), failing_command="make test")
    for body in (
        render_dockerfile(recipe),
        render_repro_script(recipe),
        render_compose(recipe),
        render_nix_flake(recipe),
    ):
        assert "Generated by devrepro" in body
        assert "REVIEW BEFORE RUNNING" in body


def test_the_script_says_that_success_is_failure() -> None:
    """The counter-intuitive part, and the reason a green tick misleads here.

    A recipe that exits zero has not reproduced the bug. Somebody reading an
    exit code without this will draw the opposite conclusion from the right one.
    """
    body = render_repro_script(build_reproduction(report(), failing_command="pytest"))
    assert "NOT REPRODUCED" in body
    assert "REPRODUCED" in body
    assert "A different failure is not" in body


def test_the_script_warns_that_a_different_failure_is_not_a_reproduction() -> None:
    body = render_repro_script(build_reproduction(report(), failing_command="pytest"))
    assert "usual way this wastes time" in body


def test_compose_starts_nothing_nobody_declared() -> None:
    """A Postgres nobody asked for is one more thing that can fail wrongly."""
    body = render_compose(build_reproduction(report()))
    assert "No additional services" in body


def test_compose_wires_declared_services() -> None:
    body = render_compose(build_reproduction(report()), services=(("postgres", 5432),))
    assert "postgres:" in body
    assert '"5432:5432"' in body
    assert "REVIEW: pin this" in body


def test_the_devcontainer_opens_a_shell_rather_than_running_the_failure() -> None:
    payload = json.loads(render_devcontainer(build_reproduction(report(), failing_command="x")))
    assert "Opens a shell" in payload["//"]
    assert payload["//failing-command"] == "x"


def test_the_flake_is_a_devshell_not_a_build() -> None:
    """A flake claiming to build the project would claim to understand the build."""
    body = render_nix_flake(build_reproduction(report()))
    assert "devShells" in body
    assert "packages.${system}" not in body


def test_the_flake_says_its_input_is_a_moving_target() -> None:
    body = render_nix_flake(build_reproduction(report()))
    assert "nixos-unstable` is a moving target" in body


# ================================================================ adapters


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_every_adapter_returns_the_filename_the_tool_looks_for(name: str) -> None:
    """Correct content under the wrong name is a file that does nothing."""
    filename, content = render_adapter(name, build_reproduction(report(), failing_command="x"))
    assert filename == ADAPTERS[name][0]
    assert content.strip()


def test_an_unknown_sandbox_is_refused_with_the_list() -> None:
    with pytest.raises(ValueError, match="daytona"):
        render_adapter("nonexistent", build_reproduction(report()))


def test_the_e2b_template_does_not_run_the_failure_at_build_time() -> None:
    """E2B starts sessions from a template rather than running it."""
    _name, content = render_adapter(
        "e2b", build_reproduction(report(), failing_command="pytest -q")
    )
    assert "belongs in the session" in content
    assert '# CMD ["sh", "-c"' in content


def test_the_container_use_adapter_marks_itself_a_draft() -> None:
    _name, content = render_adapter("container-use", build_reproduction(report()))
    payload = json.loads(content)
    assert "REVIEW REQUIRED" in payload["//"]
    assert "not a certified configuration" in payload["//"]


# ================================================================== bisect


def dims(*names: str) -> tuple[Dimension, ...]:
    return tuple(Dimension(n, "old", "new") for n in names)


def only(culprit: str):
    """A verdict function where exactly one dimension causes the failure."""

    def fails(candidate: tuple[Dimension, ...]) -> bool:
        return any(d.name == culprit for d in candidate)

    return fails


def test_bisect_finds_the_single_responsible_dimension() -> None:
    result = bisect_dimensions(dims("a", "b", "c", "d", "e", "f", "g", "h"), only("f"))
    assert result.culprit is not None
    assert result.culprit.name == "f"


def test_bisect_halves_rather_than_walking() -> None:
    """log(n) verdicts, and each verdict is a human running a build."""
    result = bisect_dimensions(dims(*[str(i) for i in range(64)]), only("40"))
    assert result.culprit is not None
    assert result.verdicts < 12


def test_a_baseline_that_already_fails_is_inconclusive() -> None:
    """The 'working' environment does not work; every later verdict is noise."""
    result = bisect_dimensions(dims("a", "b"), lambda _c: True)
    assert result.culprit is None
    assert "baseline already fails" in (result.inconclusive_because or "")


def test_a_diff_that_does_not_contain_the_cause_is_inconclusive() -> None:
    """Otherwise the search converges on whichever dimension came last."""
    result = bisect_dimensions(dims("a", "b"), lambda _c: False)
    assert result.culprit is None
    assert "not in this diff" in (result.inconclusive_because or "")


def test_an_empty_diff_is_inconclusive_rather_than_a_culprit() -> None:
    assert bisect_dimensions((), lambda _c: True).culprit is None


def test_the_trail_is_kept_for_auditing() -> None:
    """A bisect that reaches a surprising answer is one somebody will want to check."""
    result = bisect_dimensions(dims("a", "b", "c", "d"), only("c"))
    assert result.trail
    assert all(isinstance(answer, bool) for _names, answer in result.trail)


# =========================================================== minimisation


def test_minimisation_finds_an_interacting_pair_bisect_cannot() -> None:
    """The answer bisection structurally cannot give.

    Two changes that are each harmless and break things together are common,
    and a bisect run against that names one of them and is wrong in a way that
    reads as right.
    """

    def fails(candidate: tuple[Dimension, ...]) -> bool:
        names = {d.name for d in candidate}
        return {"b", "e"} <= names

    result = minimise_dimensions(dims("a", "b", "c", "d", "e", "f"), fails)
    assert {d.name for d in result.minimal} == {"b", "e"}
    assert result.interacting


def test_minimisation_reduces_to_one_when_one_is_enough() -> None:
    result = minimise_dimensions(dims("a", "b", "c", "d"), only("c"))
    assert [d.name for d in result.minimal] == ["c"]
    assert not result.interacting


def test_minimisation_is_bounded_and_says_when_the_bound_bit() -> None:
    """Each verdict is a human applying a change and running a build.

    An unbounded search is one that gets abandoned halfway with nothing to
    show, and returning a truncated result as 'minimal' would be the dishonest
    version.
    """

    def fails(candidate: tuple[Dimension, ...]) -> bool:
        return len(candidate) >= 8

    result = minimise_dimensions(dims(*[str(i) for i in range(40)]), fails, max_verdicts=6)
    assert result.inconclusive_because is not None
    assert "may not be minimal" in result.inconclusive_because


def test_nothing_to_minimise_is_reported_as_such() -> None:
    result = minimise_dimensions(dims("a", "b"), lambda _c: False)
    assert result.minimal == ()
    assert "nothing here to minimise" in (result.inconclusive_because or "")


# ================================================================== corpus


def attempt(outcome: str) -> Attempt:
    return Attempt(outcome=outcome, recorded_at="2026-01-01T00:00:00+00:00")


def test_an_unknown_outcome_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="unknown outcome"):
        record_attempt(tmp_path, attempt("worked-ish"))


def test_attempts_round_trip(tmp_path: Path) -> None:
    record_attempt(tmp_path, attempt("reproduced"))
    record_attempt(tmp_path, attempt("not-reproduced"))
    assert [a.outcome for a in read_corpus(tmp_path)] == ["reproduced", "not-reproduced"]


def test_no_rate_is_reported_below_the_sample_floor(tmp_path: Path) -> None:
    """A percentage from four attempts is a number somebody will quote."""
    for _ in range(4):
        record_attempt(tmp_path, attempt("reproduced"))
    summary = summarise(read_corpus(tmp_path))
    assert summary.rate is None
    assert str(MINIMUM_SAMPLE) in summary.caveat


def test_a_different_failure_counts_as_not_reproduced(tmp_path: Path) -> None:
    """The choice that decides whether the number is honest.

    A recipe that built, ran and produced some other error has reproduced
    nothing. Counting it as a success is how every vendor benchmark reaches 95%.
    """
    for _ in range(5):
        record_attempt(tmp_path, attempt("reproduced"))
    for _ in range(5):
        record_attempt(tmp_path, attempt("different-failure"))

    summary = summarise(read_corpus(tmp_path))

    assert summary.rate == 0.5
    assert "counting it as success" in summary.caveat


def test_the_summary_says_nothing_is_uploaded(tmp_path: Path) -> None:
    for _ in range(MINIMUM_SAMPLE):
        record_attempt(tmp_path, attempt("reproduced"))
    assert "nothing is uploaded" in summarise(read_corpus(tmp_path)).caveat


def test_every_outcome_is_documented() -> None:
    assert all(text.strip() for text in OUTCOMES.values())


def test_a_malformed_corpus_line_fails_loudly(tmp_path: Path) -> None:
    record_attempt(tmp_path, attempt("reproduced"))
    with (tmp_path / "reproductions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("not json" + NL)
    with pytest.raises(CorpusError, match="line 2"):
        read_corpus(tmp_path)


def test_an_empty_corpus_is_not_an_error(tmp_path: Path) -> None:
    assert read_corpus(tmp_path) == ()
    assert summarise(()).total == 0


# ============================================== the check that could only fail


def test_a_regenerated_recipe_compares_equal_to_itself() -> None:
    """Found by running the round trip: `--check` failed the instant after writing.

    The header carries a scan timestamp, so the emitted bytes differed on every
    run and a staleness check could only ever fail. Dropping the timestamp would
    have made the files comparable and cost the provenance -- and a generated
    artefact with no date is the one found in a wiki two years later and
    followed. So the timestamp stays and the comparison ignores it.
    """
    from devrepro.reproduce.emit import strip_provenance

    first = render_dockerfile(build_reproduction(report()))
    second = render_dockerfile(
        build_reproduction(
            ScanReport(
                schema_version="1.0",
                devrepro_version="0.2.0",
                created_at=datetime(2027, 9, 9, tzinfo=UTC),  # an hour later, or a year
                platform=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
            )
        )
    )

    assert first != second
    assert strip_provenance(first) == strip_provenance(second)


def test_a_recipe_that_describes_something_else_is_not_equal() -> None:
    """Stale means what it describes changed, not that it was regenerated."""
    from devrepro.reproduce.emit import strip_provenance

    a = render_dockerfile(build_reproduction(report()))
    b = render_dockerfile(
        build_reproduction(report(requirements=(requirement("python", "python", ">=3.12"),)))
    )
    assert strip_provenance(a) != strip_provenance(b)


def test_the_timestamp_is_still_in_the_emitted_file() -> None:
    assert "Scanned at:" in render_dockerfile(build_reproduction(report()))
