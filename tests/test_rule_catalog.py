"""The rule catalogue must describe ids the code emits, and only those.

A catalogue is documentation that ages, so these tests hold it against the
source. The first version crossed every pack with every suffix and produced
`ai-gpu/version-mismatch` and `wsl/missing`, which nothing emits -- those two
packs never call the version helpers. Over-approximating is the exact fault the
catalogue exists to avoid.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from devrepro.rules.base import PACK_NAMES
from devrepro.rules.catalog import (
    MANAGER_CONFLICT_ECOSYSTEMS,
    VERSION_CHECKING_PACKS,
    VERSION_SUFFIXES,
    RuleDoc,
    all_rule_docs,
    explain_rule,
    known_rule_ids,
)

PACKS_DIR = Path(__file__).resolve().parent.parent / "devrepro" / "rules" / "packs"
DEVREPRO = Path(__file__).resolve().parent.parent / "devrepro"

_VERSION_HELPERS = ("runtime_findings", "tool_findings", "check_version_requirement")

#: A *call* to one of the helpers, not a mention of its name. `\w` includes the
#: underscore, so the lookbehind rejects `_runtime_findings(` -- a pack's own
#: private helper whose name merely ends with one of these. Matching the bare
#: substring classified the `lockfiles` pack as version-checking on the strength
#: of a local function name, which would have made the catalogue advertise five
#: ids that pack cannot emit.
_HELPER_CALL = re.compile(r"(?<!\w)(?:" + "|".join(_VERSION_HELPERS) + r")\(")


def test_version_checking_packs_matches_the_pack_sources() -> None:
    """Every pack that calls a version helper is listed, and no others.

    If a pack starts or stops checking versions, this fails rather than letting
    the catalogue quietly advertise ids nothing produces.
    """
    actual = set()
    for module in PACKS_DIR.glob("*.py"):
        if module.stem in {"__init__", "common"}:
            continue
        text = module.read_text(encoding="utf-8")
        if _HELPER_CALL.search(text):
            actual.add(module.stem.replace("_", "-"))

    listed = set(VERSION_CHECKING_PACKS)
    assert listed == actual, (
        f"listed but does not check versions: {sorted(listed - actual)}; "
        f"checks versions but not listed: {sorted(actual - listed)}"
    )


def test_version_checking_packs_are_real_packs() -> None:
    assert set(VERSION_CHECKING_PACKS) <= set(PACK_NAMES)


def test_manager_conflict_ecosystems_match_the_probe() -> None:
    """The prefixes for `manager-conflict` come from a map in the probe.

    They are not pack names, which is why the catalogue keeps them separate.
    """
    source = (DEVREPRO / "probes" / "shell_profiles.py").read_text(encoding="utf-8")
    after = source.split("multi_manager_conflict = {", 1)[1]
    # Stop at the dict's own closing brace, not at the first inner set literal:
    # each value is itself a `{...}`, so splitting on "}" ends after one key.
    block = after.split(chr(10) + "        }", 1)[0]
    found = set(re.findall(r'"([a-z]+)":\s*\{', block))
    assert set(MANAGER_CONFLICT_ECOSYSTEMS) == found, (
        f"catalogue lists {sorted(MANAGER_CONFLICT_ECOSYSTEMS)}, probe defines {sorted(found)}"
    )


def test_every_documented_id_has_a_doc() -> None:
    ids = known_rule_ids()
    assert ids, "the catalogue is empty"
    for rule_id in ids:
        assert explain_rule(rule_id) is not None, f"{rule_id} listed but not explained"


def test_catalogue_does_not_list_ids_no_pack_can_emit() -> None:
    """The regression this file was written for."""
    ids = set(known_rule_ids())
    for pack in set(PACK_NAMES) - set(VERSION_CHECKING_PACKS):
        for suffix in VERSION_SUFFIXES:
            assert f"{pack}/{suffix}" not in ids, (
                f"{pack}/{suffix} is documented, but the {pack} pack never calls a version helper"
            )


def test_literal_ids_appear_in_the_source() -> None:
    """A documented literal id must be written somewhere in the package.

    Composed ids are excluded: their prefix is a runtime value, so the full
    string never appears in the source by construction.
    """
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in DEVREPRO.rglob("*.py")
    )
    composed_suffixes = {
        *VERSION_SUFFIXES,
        "manager-conflict",
        "multiple-installations",
        "shim-bypassed",
        "known-advisory",
        "cache-credential-committed",
        "runtime-too-old",
        "runtime-ok",
        "runtime-missing",
        "needs-toolchain",
    }
    for rule_id in known_rule_ids():
        _, _, suffix = rule_id.partition("/")
        if suffix in composed_suffixes:
            continue
        assert f'"{rule_id}"' in blob, f"{rule_id} is documented but appears nowhere in the code"


def test_composed_ids_resolve_for_any_prefix() -> None:
    """`multiple-installations` takes any detected tool name as its prefix."""
    for tool in ("kubectl", "bun", "pnpm", "uv", "some-future-tool"):
        doc = explain_rule(f"{tool}/multiple-installations")
        assert doc is not None
        assert doc.rule_id == f"{tool}/multiple-installations"


def test_unknown_ids_are_not_invented() -> None:
    assert explain_rule("nope/nope") is None
    assert explain_rule("") is None
    assert explain_rule("no-slash") is None


@pytest.mark.parametrize("doc", all_rule_docs(), ids=lambda d: d.rule_id)
def test_every_doc_is_actually_written(doc: RuleDoc) -> None:
    """Placeholder text in a catalogue is worse than an absent entry.

    `fix` is exempt from the length floor on purpose: for a PASS/INFO rule the
    honest fix really is "No action needed", and padding that to satisfy a
    threshold would make the catalogue worse, not better.
    """
    assert doc.title and not doc.title.endswith(".")
    for field in ("means", "matters"):
        value = getattr(doc, field)
        assert len(value) > 20, f"{doc.rule_id}: {field} is too short to be useful"
    for field in ("means", "matters", "fix"):
        value = getattr(doc, field)
        assert value.strip(), f"{doc.rule_id}: {field} is empty"
        assert "TODO" not in value and "TBD" not in value
        # A sentence may legitimately open with a code span --
        # "`wsl --install` if the project needs it" is correct prose, and so is
        # "`.gitmodules` names submodules...". The first version of this also
        # required the span's first character to be a letter, which rejected
        # every dotfile: a rule about capitalisation should not care what is
        # inside the backticks.
        first = value[:1]
        assert first.isupper() or first == "`", f"{doc.rule_id}: {field} should read as a sentence"


def test_the_advisory_prefix_domain_matches_the_bundled_data() -> None:
    """The catalogue's list of advisory-carrying tools is not maintained by hand.

    `ADVISORY_TOOLS` exists so `devrepro rules --catalog` can enumerate
    `<tool>/known-advisory`. It is a second copy of what the bundled advisory
    set covers, and a second copy that nothing checks is a second copy that
    drifts -- which here means an emittable rule id vanishing from the
    catalogue the moment somebody adds an advisory for a new tool.
    """
    from devrepro.compliance.advisories import bundled_bundle
    from devrepro.rules.catalog import ADVISORY_TOOLS

    assert set(ADVISORY_TOOLS) == set(bundled_bundle().covers)


def test_the_cache_credential_prefix_domain_matches_the_detector() -> None:
    """The catalogue's orchestrator list is a second copy of the detector's.

    A second copy nothing checks is a second copy that drifts, and here the
    drift means an emittable rule id quietly leaving the catalogue the moment
    somebody adds support for another build tool.
    """
    from devrepro.project.buildtools import BUILD_TOOLS
    from devrepro.rules.catalog import CACHE_CREDENTIAL_TOOLS

    modelled = {tool for _config, tool in BUILD_TOOLS}
    assert set(CACHE_CREDENTIAL_TOOLS) <= modelled


def test_the_framework_prefix_domain_matches_the_detector() -> None:
    """The catalogue's framework list is a second copy of the detector's.

    Three frameworks, deeply, rather than ten shallowly -- which makes the list
    short enough to enumerate and exactly long enough to drift.
    """
    from devrepro.project.frameworks import (
        DJANGO_PYTHON_FLOOR,
        NEXT_NODE_FLOOR,
        SPRING_BOOT_JDK_FLOOR,
    )
    from devrepro.rules.catalog import FRAMEWORK_NAMES

    assert set(FRAMEWORK_NAMES) == {"next", "django", "spring-boot"}
    # Each modelled framework must actually have floors behind it, or the
    # catalogue advertises a rule id nothing can emit.
    assert NEXT_NODE_FLOOR and DJANGO_PYTHON_FLOOR and SPRING_BOOT_JDK_FLOOR


def test_the_native_package_domain_matches_the_table() -> None:
    from devrepro.project.frameworks import NATIVE_BUILD_DEPENDENCIES
    from devrepro.rules.catalog import NATIVE_PACKAGES

    assert set(NATIVE_PACKAGES) == set(NATIVE_BUILD_DEPENDENCIES)
