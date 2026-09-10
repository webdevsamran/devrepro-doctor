"""Whether the update bot is watching the files that pin your toolchain.

Dependabot and Renovate are configured once, early, by whoever set the
repository up, and then nobody looks at the config again. What they update is
dependencies -- because that is what the templates cover -- and the toolchain
pins sit right beside them, unwatched: `.nvmrc`, `.python-version`,
`.tool-versions`, `global.json`, `rust-toolchain.toml`, the `FROM` line, the
action SHAs. Those are the files this project spends its life diagnosing
mismatches in.

The gap is not symmetrical, and that is the finding worth having:

- **Dependabot has no ecosystem for a version-manager pin at all.** There is no
  `package-ecosystem` value that reads `.nvmrc` or `.tool-versions`. A
  repository with a full `dependabot.yml` and a `.nvmrc` has a Node version
  that nothing will ever bump, and the config gives no hint of it.
- **Renovate does cover them**, via its `nvm` and `asdf` managers, which are on
  by default -- unless `enabledManagers` is set, which turns the list into an
  allowlist and silently switches off everything absent from it.

So the check is: which pin files exist, and which of them the configured bot
can actually see. It reads configuration and pin files already on disk and
contacts nothing.

Absence of a bot config is reported as unknown, not as a gap. Plenty of teams
update toolchains through a different mechanism entirely, and telling them
their unused bot is misconfigured is noise.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "PIN_FILES",
    "BotConfig",
    "PinCoverage",
    "PinFile",
    "analyse_pins",
    "parse_dependabot",
    "parse_renovate",
]

#: Files that pin a toolchain, with the Renovate manager and the Dependabot
#: ecosystem that can update each. `None` means no such thing exists -- which
#: for Dependabot is the common case and the whole point of the check.
PIN_FILES: tuple[tuple[str, str, str | None, str | None], ...] = (
    # (glob, kind, renovate manager, dependabot ecosystem)
    (".nvmrc", "node-version", "nvm", None),
    (".node-version", "node-version", "nodenv", None),
    (".python-version", "python-version", "pyenv", None),
    (".ruby-version", "ruby-version", "ruby-version", None),
    (".tool-versions", "multi-tool", "asdf", None),
    ("mise.toml", "multi-tool", "mise", None),
    (".mise.toml", "multi-tool", "mise", None),
    ("rust-toolchain.toml", "rust-version", None, None),
    ("global.json", "dotnet-sdk", None, None),
    ("Dockerfile", "base-image", "dockerfile", "docker"),
    ("docker-compose.yml", "base-image", "docker-compose", "docker"),
    (".github/workflows", "action-pins", "github-actions", "github-actions"),
)


@dataclass(frozen=True)
class PinFile:
    """A toolchain pin that exists in this repository."""

    path: str
    kind: str
    renovate_manager: str | None
    dependabot_ecosystem: str | None


@dataclass(frozen=True)
class BotConfig:
    """A bot's configuration, as far as it affects toolchain pins."""

    kind: str
    path: str
    #: Dependabot: the `package-ecosystem` values declared.
    ecosystems: tuple[str, ...] = ()
    #: Renovate: `enabledManagers`, when set. Empty means unset, which means
    #: every manager is on -- the opposite of what an empty list looks like.
    enabled_managers: tuple[str, ...] = ()
    #: Renovate: whether `enabledManagers` was present at all.
    restricts_managers: bool = False


_DEPENDABOT_ECOSYSTEM = re.compile(r"^\s*-?\s*package-ecosystem:\s*[\"']?([\w.-]+)", re.MULTILINE)


def parse_dependabot(text: str) -> tuple[str, ...]:
    """The `package-ecosystem` values in a `dependabot.yml`.

    Read with a regex rather than a YAML parser, for the same reason the CI
    workflow parser is: this project has no YAML dependency, and the one field
    that matters here is a flat scalar under a list item. A file too exotic for
    this yields no ecosystems, which reports as unknown rather than as a gap.
    """
    return tuple(dict.fromkeys(m.group(1) for m in _DEPENDABOT_ECOSYSTEM.finditer(text)))


def parse_renovate(text: str) -> tuple[tuple[str, ...], bool]:
    """`enabledManagers` from a Renovate config, and whether it was present.

    The two are separate answers. An absent `enabledManagers` means every
    manager runs, so the pins are covered; an empty one would mean none do.
    Collapsing both into an empty tuple gets the safer-looking answer exactly
    backwards.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Renovate accepts JSON5 and comments. Rather than half-parse it, strip
        # line comments and retry once; anything still unreadable is reported
        # as unknown, which is honest and does not produce a false gap.
        stripped = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return (), False
    if not isinstance(payload, dict):
        return (), False
    managers = payload.get("enabledManagers")
    if not isinstance(managers, list):
        return (), False
    return tuple(str(m) for m in managers), True


def _bot_configs(root: Path) -> tuple[BotConfig, ...]:
    found: list[BotConfig] = []

    dependabot = root / ".github" / "dependabot.yml"
    if not dependabot.is_file():
        dependabot = root / ".github" / "dependabot.yaml"
    if dependabot.is_file():
        with suppress(OSError):  # an unreadable config reports as unknown
            found.append(
                BotConfig(
                    kind="dependabot",
                    path=str(dependabot.relative_to(root)).replace("\\", "/"),
                    ecosystems=parse_dependabot(dependabot.read_text(encoding="utf-8")),
                )
            )

    for candidate in ("renovate.json", ".renovaterc.json", ".github/renovate.json"):
        path = root / candidate
        if not path.is_file():
            continue
        try:
            managers, restricts = parse_renovate(path.read_text(encoding="utf-8"))
        except OSError:  # pragma: no cover - unreadable config
            continue
        found.append(
            BotConfig(
                kind="renovate",
                path=candidate,
                enabled_managers=managers,
                restricts_managers=restricts,
            )
        )
        break

    return tuple(found)


def _pins_present(root: Path) -> tuple[PinFile, ...]:
    present: list[PinFile] = []
    for name, kind, manager, ecosystem in PIN_FILES:
        path = root / name
        exists = path.is_dir() if name.endswith("workflows") else path.is_file()
        if exists:
            present.append(PinFile(name, kind, manager, ecosystem))
    return tuple(present)


@dataclass(frozen=True)
class PinCoverage:
    """Which toolchain pins the configured bots can actually update."""

    bots: tuple[BotConfig, ...]
    pins: tuple[PinFile, ...]
    covered: tuple[PinFile, ...]
    uncovered: tuple[PinFile, ...]

    @property
    def configured(self) -> bool:
        return bool(self.bots)


def analyse_pins(root: Path) -> PinCoverage:
    """Compare the pins in this repository against what the bots are set to watch."""
    bots = _bot_configs(root)
    pins = _pins_present(root)

    if not bots:
        # No bot at all means no answer, not a gap. Reporting every pin as
        # uncovered here would tell a team that updates toolchains by hand that
        # their non-existent bot is misconfigured.
        return PinCoverage(bots=(), pins=pins, covered=(), uncovered=())

    dependabot = next((b for b in bots if b.kind == "dependabot"), None)
    renovate = next((b for b in bots if b.kind == "renovate"), None)

    covered: list[PinFile] = []
    uncovered: list[PinFile] = []
    for pin in pins:
        by_dependabot = (
            dependabot is not None
            and pin.dependabot_ecosystem is not None
            and pin.dependabot_ecosystem in dependabot.ecosystems
        )
        by_renovate = renovate is not None and pin.renovate_manager is not None
        if by_renovate and renovate is not None and renovate.restricts_managers:
            by_renovate = pin.renovate_manager in renovate.enabled_managers
        (covered if (by_dependabot or by_renovate) else uncovered).append(pin)

    return PinCoverage(bots=bots, pins=pins, covered=tuple(covered), uncovered=tuple(uncovered))
