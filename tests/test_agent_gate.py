"""The badge, the gate, the token estimate and sandbox parity.

Four ways of putting the same scan in front of somebody who is about to make a
decision: a reader glancing at a README, an agent runner deciding whether to
start, a manager deciding whether documentation is worth an afternoon, and a
build about to be killed by an OOM killer that writes nothing to the log.

Each has a way of being dishonest and each test below is aimed at that. A badge
that flatters. A gate that fires on every repository and gets deleted. An
estimate presented as a measurement. A parity check that fires when it simply
could not tell.
"""

from __future__ import annotations

from devrepro.agents.badge import BADGE_COLOURS, badge_markdown, badge_payload
from devrepro.agents.blast_radius import BlastRadius, Exposure
from devrepro.agents.gate import (
    DEFAULT_THRESHOLD,
    claude_code_hook,
    evaluate_gate,
    generic_hook_script,
)
from devrepro.agents.sandbox import (
    OOM_EXIT_CODE,
    SandboxLimits,
    compare_limits,
    parse_compose_limits,
    parse_devcontainer_limits,
    parse_memory_value,
)
from devrepro.agents.score import AgentReadiness, ReadinessFactor
from devrepro.agents.tokencost import COST_MODEL, TOKENS_PER_TURN, estimate_token_cost

NL = chr(10)
GIB = 1024**3


def readiness(percent: int) -> AgentReadiness:
    """A score with the requested percentage, and one failing factor to name."""
    total = percent
    return AgentReadiness(
        total=total,
        possible=100,
        factors=(
            ReadinessFactor("manifest-present", 3, 3, "found"),
            ReadinessFactor("commands-run", 0, 5, "two do not resolve"),
        ),
    )


def radius(*exposures: Exposure) -> BlastRadius:
    return BlastRadius(
        root=".",
        exposures=exposures,
        uncommitted_files=0,
        unpushed_commits=0,
        credential_names=(),
    )


# ==================================================================== badge


def test_the_badge_is_a_shields_endpoint_not_a_static_image() -> None:
    """A committed SVG is still green two years after it stopped being true."""
    payload = badge_payload(readiness(95))
    assert payload["schemaVersion"] == 1
    assert set(payload) == {"schemaVersion", "label", "message", "color"}


def test_the_message_carries_the_grade_as_well_as_the_number() -> None:
    """A number alone invites the reader to supply their own threshold."""
    assert badge_payload(readiness(95))["message"] == "95% ready"


def test_the_middle_of_the_range_is_not_green() -> None:
    """Green at 60% is a choice to make a mediocre score look fine."""
    assert badge_payload(readiness(95))["color"] == "brightgreen"
    assert badge_payload(readiness(70))["color"] == "yellow"
    assert badge_payload(readiness(40))["color"] == "orange"
    assert badge_payload(readiness(10))["color"] == "red"


def test_every_grade_has_a_colour() -> None:
    """A grade with no entry renders grey, which reads as broken."""
    for percent in (95, 70, 40, 10):
        assert readiness(percent).grade in BADGE_COLOURS


def test_the_markdown_takes_the_url_rather_than_inventing_one() -> None:
    """A badge pointing at a guessed URL renders 'invalid' for everybody."""
    markdown = badge_markdown("https://example.invalid/badge.json")
    assert "img.shields.io/endpoint?url=" in markdown
    assert "https%3A%2F%2Fexample.invalid%2Fbadge.json" in markdown


# ===================================================================== gate


def test_a_ready_repository_is_allowed() -> None:
    verdict = evaluate_gate(readiness(90))
    assert verdict.allowed
    assert verdict.reasons == ()


def test_a_low_score_blocks_and_names_the_weakest_factors() -> None:
    verdict = evaluate_gate(readiness(20))
    assert not verdict.allowed
    assert "commands-run" in verdict.reasons[0]


def test_the_threshold_is_a_threshold_not_any_finding() -> None:
    """A gate that fires on every repository is one removed in week one.

    The same reasoning produced `guard --scope changed`, and it is the
    difference between a check people keep and a check people delete.
    """
    assert DEFAULT_THRESHOLD == 60
    assert evaluate_gate(readiness(61)).allowed
    assert not evaluate_gate(readiness(59)).allowed


def test_a_well_prepared_repository_with_production_access_still_blocks() -> None:
    """The worst case, not a safe one.

    Readiness asks whether the agent can get work done. Blast radius asks what
    it reaches if it goes wrong. A clean, well-documented checkout with
    production credentials scores well on the first and is the most dangerous
    place to start, because everything about it invites confidence.
    """
    verdict = evaluate_gate(
        readiness(95),
        blast_radius=radius(
            Exposure(
                kind="production-context",
                severity="high",
                summary="prod",
                detail="AWS_PROFILE names a production account",
            )
        ),
    )
    assert not verdict.allowed
    assert "production-adjacent" in verdict.reasons[0]


def test_production_blocking_can_be_turned_off_deliberately() -> None:
    verdict = evaluate_gate(
        readiness(95),
        blast_radius=radius(
            Exposure(kind="production-context", severity="high", summary="p", detail="d")
        ),
        block_on_production=False,
    )
    assert verdict.allowed


def test_the_claude_hook_runs_once_per_session_not_per_tool() -> None:
    """A per-tool hook would re-scan the machine on every single tool call."""
    hook = claude_code_hook()
    assert "SessionStart" in hook
    assert "PreToolUse" not in hook
    assert "--gate" in hook


def test_the_shell_hook_is_a_wrapper_not_a_profile_edit() -> None:
    """Something that gates every shell is something people fight at the worst moment."""
    script = generic_hook_script()
    assert script.startswith("#!/usr/bin/env bash")
    assert 'exec "$@"' in script
    assert ".bashrc" not in script


def test_the_hook_carries_the_threshold_it_was_generated_with() -> None:
    assert "--threshold 80" in claude_code_hook(threshold=80)
    assert "--threshold 80" in generic_hook_script(threshold=80)


# ============================================================== token cost


def test_a_prepared_repository_costs_nothing() -> None:
    estimate = estimate_token_cost(
        manifests=[object()], checks=[], stale=[], drift=[], disagreements=[]
    )
    assert estimate.turns == 0
    assert estimate.rounded_tokens == 0


def test_every_signal_contributes_and_says_why() -> None:
    class Check:
        ok = False

    estimate = estimate_token_cost(
        manifests=[],
        checks=[Check(), Check()],
        stale=[object()],
        drift=["ruff check"],
        disagreements=[object()],
    )
    signals = {name for name, _count, _each, _why in estimate.contributions}
    assert signals == {name for name, _turns, _why in COST_MODEL}
    assert all(why.strip() for _n, _c, _e, why in estimate.contributions)


def test_the_estimate_is_rounded_hard() -> None:
    """43,712 tokens implies a measurement nobody made."""

    class Check:
        ok = False

    estimate = estimate_token_cost(
        manifests=[object()], checks=[Check()], stale=[], drift=[], disagreements=[]
    )
    assert estimate.tokens == 3 * TOKENS_PER_TURN
    assert estimate.rounded_tokens % 5_000 == 0


def test_the_payload_carries_the_caveat_and_the_assumption() -> None:
    """The number leaves this process; the reasoning has to travel with it."""
    payload = estimate_token_cost(
        manifests=[], checks=[], stale=[], drift=[], disagreements=[]
    ).as_dict()
    assert "not a measurement" in payload["caveat"]
    assert payload["tokens_per_turn_assumed"] == TOKENS_PER_TURN


def test_no_price_is_attached() -> None:
    """Model pricing changes monthly; a stale dollar figure is worse than none."""
    payload = estimate_token_cost(
        manifests=[], checks=[], stale=[], drift=[], disagreements=[]
    ).as_dict()
    assert "$" not in str(payload)
    assert "usd" not in str(payload).lower()


# =========================================================== sandbox parity


def test_decimal_and_binary_memory_units_are_not_the_same() -> None:
    """`2g` is 2*1000^3 and `2gb` is 2*1024^3.

    A parser that conflates them is off by 7%, which is enough to put a limit
    on the wrong side of a threshold and never enough for anybody to notice.
    """
    assert parse_memory_value("2g") == 2 * 1000**3
    assert parse_memory_value("2gb") == 2 * 1024**3
    assert parse_memory_value(4096) == 4096
    assert parse_memory_value(None) is None
    assert parse_memory_value("lots") is None


def test_both_compose_spellings_are_read() -> None:
    """Real compose files carry one of each, because they were migrated halfway."""
    v2 = parse_compose_limits("services:" + NL + "  app:" + NL + "    mem_limit: 2g" + NL)
    assert v2.memory_bytes == 2 * 1000**3

    v3 = parse_compose_limits(
        "services:"
        + NL
        + "  app:"
        + NL
        + "    deploy:"
        + NL
        + "      resources:"
        + NL
        + "        limits:"
        + NL
        + "          memory: 512m"
        + NL
    )
    assert v3.memory_bytes == 512 * 1000**2


def test_a_disabled_network_is_detected_in_compose() -> None:
    limits = parse_compose_limits("services:" + NL + "  app:" + NL + "    network_mode: none" + NL)
    assert limits.network_disabled is True


def test_a_compose_file_with_no_limits_declares_nothing() -> None:
    limits = parse_compose_limits("services:" + NL + "  app:" + NL + "    image: python" + NL)
    assert limits.declares_anything is False


def test_devcontainer_runargs_are_read_through_comments() -> None:
    """`devcontainer.json` is JSON with comments, which `json` refuses."""
    limits = parse_devcontainer_limits(
        "// our devcontainer" + NL + '{"runArgs": ["--memory=4g", "--cpus", "2"]}'
    )
    assert limits.memory_bytes == 4 * 1000**3
    assert limits.cpus == 2.0


def test_an_unparseable_devcontainer_declares_nothing_rather_than_guessing() -> None:
    assert parse_devcontainer_limits("{{{").declares_anything is False


def test_a_tight_memory_limit_names_the_exit_code_nobody_recognises() -> None:
    """137 is 128 + SIGKILL and is the only trace the OOM killer leaves."""
    findings = compare_limits(
        host_memory_bytes=32 * GIB,
        host_cpus=16,
        engine_memory_bytes=2 * GIB,
    )
    memory = next(f for f in findings if f.kind == "memory")
    assert str(OOM_EXIT_CODE) in memory.detail
    assert "compiler crash" in memory.detail


def test_a_reasonable_engine_limit_is_not_reported() -> None:
    """Plenty of containers are deliberately smaller than the host."""
    findings = compare_limits(
        host_memory_bytes=32 * GIB, host_cpus=16, engine_memory_bytes=24 * GIB
    )
    assert [f.kind for f in findings if f.kind == "memory"] == []


def test_fewer_cores_is_reported_as_thrash_not_failure() -> None:
    """The build finishes; it just takes three times as long, for no logged reason."""
    findings = compare_limits(host_memory_bytes=None, host_cpus=16, engine_cpus=2)
    cpu = next(f for f in findings if f.kind == "cpu")
    assert "thrashes" in cpu.detail
    assert "nproc" in cpu.detail


def test_the_tightest_declaration_wins() -> None:
    """An engine limit and a compose limit both apply; the smaller one is the box."""
    findings = compare_limits(
        host_memory_bytes=32 * GIB,
        host_cpus=16,
        engine_memory_bytes=16 * GIB,
        declared=(SandboxLimits(source="compose", memory_bytes=1 * GIB),),
    )
    assert any(f.kind == "memory" for f in findings)


def test_a_disabled_network_conflicts_with_a_build_that_fetches() -> None:
    findings = compare_limits(
        host_memory_bytes=None,
        host_cpus=None,
        declared=(SandboxLimits(source="compose", network_disabled=True),),
        needs_network=True,
    )
    network = next(f for f in findings if f.kind == "network")
    assert "neither knows about the other" in network.detail


def test_unknown_host_figures_produce_no_findings() -> None:
    """A missing /proc/meminfo is not evidence that the sandbox is small."""
    assert compare_limits(host_memory_bytes=None, host_cpus=None, engine_memory_bytes=1) == ()


def test_every_parity_finding_carries_a_remedy() -> None:
    findings = compare_limits(
        host_memory_bytes=32 * GIB, host_cpus=16, engine_memory_bytes=1 * GIB, engine_cpus=1
    )
    assert findings
    assert all(f.remedy for f in findings)
