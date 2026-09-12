"""Numbers in the README are claims, and claims go stale.

`ROADMAP.md` has been checked against the real command count for a while; the
README had the same numbers and nothing checking them. That asymmetry is how a
document ends up advertising 37 commands for a tool that has 55 -- the count is
right on the day it is written and wrong on the day somebody adds a command,
which is exactly when nobody rereads the README.

The README is also the first and most-read thing about this project. If any
file here has to be true, it is that one.
"""

from __future__ import annotations

import re
from pathlib import Path

from devrepro.cli.app import app
from devrepro.rules.base import PACK_NAMES
from devrepro.rules.catalog import all_rule_docs

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")


def _command_count() -> int:
    return len(app.registered_commands)


def test_the_readme_command_count_matches_the_cli() -> None:
    claimed = {int(n) for n in re.findall(r"\b(\d+)\s+commands\b", _README)}
    assert claimed, "README no longer states a command count"
    assert claimed == {_command_count()}, (
        f"README claims {sorted(claimed)} commands; the CLI registers "
        f"{_command_count()}. Update the README (heading and contents link)."
    )


def test_the_readme_lists_every_command_it_has() -> None:
    """The grouped block has to be the whole surface, not most of it.

    A command missing from that list is a command nobody discovers, which is
    indistinguishable from one that was never built.
    """
    block = _README.split("## All", 1)[1].split("```", 2)[1]
    listed = set(re.findall(r"\b[a-z][a-z-]{2,}\b", block))
    registered = {c.name or c.callback.__name__.rstrip("_") for c in app.registered_commands}
    missing = sorted(registered - listed)
    assert not missing, f"README's command block omits: {missing}"


def test_the_readme_rule_counts_match_the_catalogue() -> None:
    rule_ids = {int(n) for n in re.findall(r"\b(\d+)\s+documented rule ids\b", _README)}
    packs = {int(n) for n in re.findall(r"\b(\d+)\s+rule\s*\n?packs\b", _README)}
    assert rule_ids == {len(all_rule_docs())}, (
        f"README claims {sorted(rule_ids)} documented rule ids; "
        f"the catalogue has {len(all_rule_docs())}."
    )
    assert packs == {len(PACK_NAMES)}, (
        f"README claims {sorted(packs)} rule packs; {len(PACK_NAMES)} are registered."
    )


def test_the_readme_page_count_matches_the_console() -> None:
    nav = (_ROOT / "web" / "src" / "nav.ts").read_text(encoding="utf-8")
    real = len(re.findall(r"\bid: '", nav))
    claimed = {int(n) for n in re.findall(r"\b(\d+)\s+pages\b", _README)}
    assert claimed == {real}, f"README claims {sorted(claimed)} console pages; nav.ts has {real}."


def test_the_readme_documents_every_exit_code() -> None:
    """`4` was missing while eight call sites used it and a guard enforced it.

    A published contract that omits one of its own codes is worse than one that
    omits all of them: a reader trusts the four they were given.
    """
    from devrepro.core.exit_codes import ExitCode

    section = _README.split("exit codes are stable", 1)[1][:400]
    for code in ExitCode:
        assert f"`{int(code)}`" in section, (
            f"README's exit-code sentence omits {int(code)} ({code.name})"
        )
