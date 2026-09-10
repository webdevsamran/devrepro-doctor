"""Build orchestrators, formatter disagreement, kubectl's context, shell cost.

Four checks with one thing in common: each is a fact somebody already wrote
down, in a file or a config, and nobody re-reads. A cache token in `nx.json`, a
`.editorconfig` that contradicts prettier, a kubectl context left pointing at
production three weeks ago, a shell profile that has accumulated four version
managers.

The care in each is about what *not* to claim. The style comparison fills in no
defaults, because a project that has not configured a width has not disagreed
with anything. The context check says its production guess is name-based, since
the alternative -- reading the cluster to be sure -- is an authenticated request
to a production cluster from a diagnostic command. The shell check counts and
does not time, because timing means running the user's own configuration.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 -- pytest resolves fixture annotations

from devrepro.platforms.kubecontext import classify_context, parse_contexts
from devrepro.platforms.shellcost import SLOW_STARTUP_THRESHOLD, analyse_profile
from devrepro.project.buildtools import detect_build_tools, read_bazelrc, read_nx, read_turbo
from devrepro.project.editorconfig import (
    compare_styles,
    read_editorconfig,
    read_prettier,
    read_ruff,
)

NL = chr(10)


def write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ======================================================== build orchestrators


def test_an_nx_cloud_token_in_a_committed_file_is_the_finding(tmp_path: Path) -> None:
    """A read-write cache token is a supply-chain credential.

    Whoever holds it can write cache entries that every developer and every CI
    run then treats as trusted build output.
    """
    path = write(tmp_path, "nx.json", '{"nxCloudAccessToken": "abc123"}')

    cache = read_nx(path)

    assert cache.credential_field == "nxCloudAccessToken"
    assert cache.remote_configured


def test_the_token_value_is_never_carried_out_of_the_reader(tmp_path: Path) -> None:
    """The finding is that a secret-shaped field is committed. The value adds nothing."""
    path = write(tmp_path, "nx.json", '{"nxCloudAccessToken": "SUPERSECRET"}')

    cache = read_nx(path)

    assert "SUPERSECRET" not in (cache.detail or "")
    assert "SUPERSECRET" not in (cache.credential_field or "")


def test_nx_cloud_without_a_committed_token_is_not_a_finding(tmp_path: Path) -> None:
    path = write(tmp_path, "nx.json", '{"nxCloudId": "org-123"}')
    cache = read_nx(path)
    assert cache.remote_configured
    assert cache.credential_field is None


def test_a_local_only_nx_reports_as_such(tmp_path: Path) -> None:
    path = write(tmp_path, "nx.json", '{"targetDefaults": {}}')
    assert read_nx(path).remote_configured is False


def test_turborepo_remote_cache_is_detected(tmp_path: Path) -> None:
    path = write(tmp_path, "turbo.json", '{"remoteCache": {"enabled": true}}')
    assert read_turbo(path).remote_configured is True


def test_a_disabled_turbo_remote_cache_is_not_configured(tmp_path: Path) -> None:
    path = write(tmp_path, "turbo.json", '{"remoteCache": {"enabled": false}}')
    assert read_turbo(path).remote_configured is False


def test_an_authorization_header_in_bazelrc_is_a_credential(tmp_path: Path) -> None:
    """`.bazelrc` reads like a flags file, which is why this ends up committed."""
    path = write(
        tmp_path,
        ".bazelrc",
        "build --remote_cache=grpcs://cache.example"
        + NL
        + "build --remote_header=Authorization=Bearer xyz"
        + NL,
    )
    cache = read_bazelrc(path)
    assert cache.credential_field == "--remote_header=Authorization"


def test_a_bazelrc_with_a_cache_and_no_header_is_only_configured(tmp_path: Path) -> None:
    path = write(tmp_path, ".bazelrc", "build --remote_cache=grpcs://cache.example" + NL)
    cache = read_bazelrc(path)
    assert cache.remote_configured
    assert cache.credential_field is None


def test_a_commented_bazelrc_line_is_not_a_configuration(tmp_path: Path) -> None:
    path = write(tmp_path, ".bazelrc", "# build --remote_cache=grpcs://cache.example" + NL)
    assert read_bazelrc(path).remote_configured is False


def test_orchestrators_are_detected_from_files_alone(tmp_path: Path) -> None:
    """Nothing is executed: `nx show projects` and `bazel info` start daemons."""
    write(tmp_path, "nx.json", "{}")
    write(tmp_path, "turbo.json", "{}")

    tools = detect_build_tools(tmp_path)

    assert {t.name for t in tools} == {"nx", "turborepo"}


def test_bazel_is_reported_once_for_two_marker_files(tmp_path: Path) -> None:
    write(tmp_path, "MODULE.bazel", "")
    write(tmp_path, "WORKSPACE", "")
    assert [t.name for t in detect_build_tools(tmp_path)] == ["bazel"]


def test_a_repository_with_no_orchestrator_reports_nothing(tmp_path: Path) -> None:
    assert detect_build_tools(tmp_path) == ()


def test_unparseable_configuration_does_not_invent_a_cache(tmp_path: Path) -> None:
    path = write(tmp_path, "nx.json", "{not json")
    assert read_nx(path).remote_configured is False


# ============================================================ formatter style


def test_the_editor_and_the_formatter_disagreeing_is_the_finding(tmp_path: Path) -> None:
    """Two tools, both behaving as configured, producing a whitespace diff."""
    write(tmp_path, ".editorconfig", "[*]" + NL + "indent_size = 2" + NL)
    write(tmp_path, ".prettierrc", '{"tabWidth": 4}')

    conflicts = compare_styles(
        (read_editorconfig(tmp_path / ".editorconfig"), read_prettier(tmp_path))
    )

    assert len(conflicts) == 1
    assert conflicts[0].setting == "indent_size"
    assert ".editorconfig" in conflicts[0].describe()


def test_agreement_produces_nothing(tmp_path: Path) -> None:
    write(tmp_path, ".editorconfig", "[*]" + NL + "indent_size = 4" + NL)
    write(tmp_path, ".prettierrc", '{"tabWidth": 4}')
    assert (
        compare_styles((read_editorconfig(tmp_path / ".editorconfig"), read_prettier(tmp_path)))
        == ()
    )


def test_an_unconfigured_setting_never_conflicts(tmp_path: Path) -> None:
    """The reason the readers refuse to fill in defaults.

    Prettier's default width is 80. A project that never set one has not
    disagreed with `.editorconfig`; reporting the default as a conflict puts an
    opinion in the project's mouth that nobody there holds.
    """
    write(tmp_path, ".editorconfig", "[*]" + NL + "max_line_length = 120" + NL)
    write(tmp_path, ".prettierrc", '{"tabWidth": 2}')

    conflicts = compare_styles(
        (read_editorconfig(tmp_path / ".editorconfig"), read_prettier(tmp_path))
    )

    assert conflicts == ()


def test_only_the_catch_all_section_is_compared(tmp_path: Path) -> None:
    """A per-glob override is a deliberate exception somebody already thought about."""
    write(
        tmp_path,
        ".editorconfig",
        "[*]" + NL + "indent_size = 4" + NL + "[*.md]" + NL + "indent_size = 2" + NL,
    )
    config = read_editorconfig(tmp_path / ".editorconfig")
    assert config is not None
    assert config.indent_size == 4


def test_indent_size_tab_is_not_read_as_a_width(tmp_path: Path) -> None:
    """`indent_size = tab` is legal EditorConfig and is not a number."""
    write(
        tmp_path, ".editorconfig", "[*]" + NL + "indent_style = tab" + NL + "indent_size = tab" + NL
    )
    config = read_editorconfig(tmp_path / ".editorconfig")
    assert config is not None
    assert config.indent_size is None
    assert config.indent_style == "tab"


def test_comments_are_ignored(tmp_path: Path) -> None:
    write(tmp_path, ".editorconfig", "[*]" + NL + "# indent_size = 2" + NL + "indent_size = 4" + NL)
    config = read_editorconfig(tmp_path / ".editorconfig")
    assert config is not None
    assert config.indent_size == 4


def test_prettier_configuration_in_package_json_is_read(tmp_path: Path) -> None:
    write(tmp_path, "package.json", '{"prettier": {"tabWidth": 8}}')
    config = read_prettier(tmp_path)
    assert config is not None
    assert config.indent_size == 8
    assert config.source == "package.json"


def test_ruff_line_length_is_read_from_pyproject(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.ruff]" + NL + "line-length = 100" + NL)
    config = read_ruff(tmp_path)
    assert config is not None
    assert config.max_line_length == 100


def test_ruff_and_the_editor_can_conflict_too(tmp_path: Path) -> None:
    write(tmp_path, ".editorconfig", "[*]" + NL + "max_line_length = 79" + NL)
    write(tmp_path, "pyproject.toml", "[tool.ruff]" + NL + "line-length = 100" + NL)

    conflicts = compare_styles((read_editorconfig(tmp_path / ".editorconfig"), read_ruff(tmp_path)))

    assert [c.setting for c in conflicts] == ["max_line_length"]


def test_an_absent_editorconfig_is_not_a_config(tmp_path: Path) -> None:
    assert read_editorconfig(tmp_path / ".editorconfig") is None


# ============================================================ kubectl context


CONTEXTS = (
    "CURRENT   NAME              CLUSTER           AUTHINFO   NAMESPACE"
    + NL
    + "          kind-local        kind-local        kind-local"
    + NL
    + "*         prod-eu-1         prod-eu-1         admin      default"
    + NL
)


def test_the_current_context_is_identified() -> None:
    contexts = parse_contexts(CONTEXTS)
    assert [c.name for c in contexts] == ["kind-local", "prod-eu-1"]
    assert [c.name for c in contexts if c.current] == ["prod-eu-1"]


def test_a_row_with_no_namespace_still_parses() -> None:
    """The table's last columns are routinely empty.

    A parser assuming five fields silently returns nothing for exactly the rows
    that have no namespace set, which is most of them.
    """
    contexts = parse_contexts(CONTEXTS)
    assert contexts[0].namespace == ""


def test_a_production_looking_context_warns() -> None:
    verdict = classify_context(parse_contexts(CONTEXTS))
    assert verdict.warn is True
    assert "persists across shells" in verdict.detail


def test_a_local_context_is_silent() -> None:
    """A warning on every developer's kind cluster is a warning nobody reads."""
    local = (
        "CURRENT   NAME         CLUSTER      AUTHINFO"
        + NL
        + "*         kind-local   kind-local   x"
        + NL
    )
    verdict = classify_context(parse_contexts(local))
    assert verdict.warn is False


def test_a_context_named_production_that_is_local_does_not_warn() -> None:
    """`kind-production` is somebody's local cluster with an unfortunate name."""
    text = (
        "CURRENT   NAME               CLUSTER            AUTHINFO"
        + NL
        + "*         kind-production    kind-production    x"
        + NL
    )
    verdict = classify_context(parse_contexts(text))
    assert verdict.warn is False


def test_a_remote_context_with_a_neutral_name_is_reported_without_warning() -> None:
    text = (
        "CURRENT   NAME       CLUSTER    AUTHINFO" + NL + "*         staging    staging    x" + NL
    )
    verdict = classify_context(parse_contexts(text))
    assert verdict.warn is False
    assert "not a local cluster" in verdict.detail


def test_no_current_context_is_reported_as_such() -> None:
    text = (
        "CURRENT   NAME       CLUSTER    AUTHINFO" + NL + "          staging    staging    x" + NL
    )
    verdict = classify_context(parse_contexts(text))
    assert verdict.current is None
    assert "no current context" in verdict.detail


# ============================================================== shell startup


PROFILE = (
    'eval "$(pyenv init -)"'
    + NL
    + 'export NVM_DIR="$HOME/.nvm"'
    + NL
    + '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"'
    + NL
    + 'eval "$(direnv hook bash)"'
    + NL
    + "__conda_setup=\"$('/opt/conda/bin/conda' shell.bash hook)\""
    + NL
)


def test_every_subshell_spawning_initialisation_is_counted() -> None:
    cost = analyse_profile("~/.bashrc", PROFILE)
    labels = [label for label, _ in cost.initialisations]
    assert "pyenv init" in labels
    assert "nvm.sh" in labels
    assert "direnv hook" in labels
    assert "conda initialize" in labels


def test_four_initialisations_is_the_threshold() -> None:
    assert analyse_profile("~/.bashrc", PROFILE).slow is True
    assert SLOW_STARTUP_THRESHOLD == 4


def test_a_light_profile_is_not_reported() -> None:
    cost = analyse_profile("~/.bashrc", 'export PATH="$HOME/bin:$PATH"' + NL)
    assert cost.count == 0
    assert cost.slow is False


def test_commented_out_lines_cost_nothing() -> None:
    """A profile somebody already pruned is full of these.

    Counting them makes the finding wrong in the direction that destroys trust
    in every other finding.
    """
    commented = NL.join("# " + line for line in PROFILE.splitlines())
    assert analyse_profile("~/.bashrc", commented).count == 0


def test_a_tool_sourced_twice_is_one_problem() -> None:
    doubled = PROFILE + '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"' + NL
    labels = [label for label, _ in analyse_profile("~/.bashrc", doubled).initialisations]
    assert labels.count("nvm.sh") == 1


def test_each_entry_says_why_it_costs() -> None:
    """ "pyenv init" alone is a name; the sentence beside it is the reason to act."""
    cost = analyse_profile("~/.bashrc", PROFILE)
    assert all(why.strip() for _, why in cost.initialisations)
    assert any("forks" in why for _, why in cost.initialisations)


def test_the_order_follows_the_file() -> None:
    """The advice is "look at these lines"; a reordered list makes the reader search."""
    labels = [label for label, _ in analyse_profile("~/.bashrc", PROFILE).initialisations]
    assert labels[0] == "pyenv init"
