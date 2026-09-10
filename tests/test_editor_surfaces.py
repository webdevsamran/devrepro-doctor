"""The editor and browser surfaces, and the promises they make in their READMEs.

None of these can be exercised end to end from a Python suite -- one needs VS
Code, one needs Chrome, one needs a JetBrains IDE. What *can* be checked is
everything that would make them broken on arrival or dishonest in the same
breath as the rest of the project:

- The manifests parse, and declare the commands their READMEs advertise.
- The browser extension asks for no permission that would let it phone home,
  and contains no code that could. It says so in its README, and a claim
  nothing enforces is a claim that decays.
- No surface offers `devrepro fix`. A menu item that runs remediations is one
  click from running them by accident, and the consent gate exists precisely so
  a person agrees each time.
- None of them needs a build step, which is the reason they can live in this
  repository at all.

The XML parsing below carries `# noqa: S314`. That rule is about untrusted
XML -- entity expansion, external entities -- and the input is a file in this
repository read by this repository's suite. Adding `defusedxml` to satisfy a
check against a threat that does not apply is a dependency bought with
nothing, so it is suppressed per-site: a future parse of somebody else's XML
still trips it.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VSCODE = ROOT / "extensions" / "vscode"
BROWSER = ROOT / "extensions" / "browser"
JETBRAINS = ROOT / "extensions" / "jetbrains"

#: `querySelector('…')`, with the quote character back-referenced: the
#: selector is single quoted and contains double quotes, so a character
#: class stops at the first inner quote and captures `[itemprop=`.
SELECTOR = re.compile(r"""querySelector\(\s*(?P<q>['"])(?P<sel>.*?)(?P=q)""")


def manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================== VS Code


def test_the_vscode_manifest_parses_and_declares_its_commands() -> None:
    payload = manifest(VSCODE / "package.json")
    commands = {c["command"] for c in payload["contributes"]["commands"]}
    assert commands == {"devrepro.scan", "devrepro.explain", "devrepro.agentCheck"}


def test_the_vscode_extension_has_no_dependencies_and_no_build() -> None:
    """The reason it can live in this repository and load directly.

    A TypeScript extension needs a compiler, a tsconfig, a bundler and a pinned
    `vscode.d.ts` -- four things to keep in step, in a project whose selling
    point is that it does not accumulate moving parts.
    """
    payload = manifest(VSCODE / "package.json")
    assert not payload.get("dependencies")
    assert not payload.get("devDependencies")
    assert payload["main"].endswith(".js")
    assert not (VSCODE / "tsconfig.json").exists()


def test_scanning_on_startup_is_off_by_default() -> None:
    """An extension that spawns processes while you open a file gets disabled."""
    properties = manifest(VSCODE / "package.json")["contributes"]["configuration"]["properties"]
    assert properties["devrepro.scanOnStartup"]["default"] is False


def test_the_extension_refuses_absolute_paths_as_diagnostic_anchors() -> None:
    """A diagnostic inside somebody's home directory is meaningless and a leak.

    It is also a username on screen during a screen-share, which is the half
    people notice.
    """
    source = (VSCODE / "extension.js").read_text(encoding="utf-8")
    assert "startsWith('/')" in source
    assert "candidate[1] === ':'" in source


def test_a_non_zero_exit_is_not_treated_as_a_failure() -> None:
    """1 means warnings and 2 means blocked; both are the contract working."""
    source = (VSCODE / "extension.js").read_text(encoding="utf-8")
    assert "if (error && !stdout)" in source


# ============================================================== browser


def test_the_browser_extension_cannot_reach_the_network() -> None:
    """The claim its README makes, enforced rather than asserted in prose.

    A hosted badge would mean an endpoint and a log of somebody's browsing
    arriving at a server -- the shape this project exists to be the opposite of.
    """
    payload = manifest(BROWSER / "manifest.json")
    assert payload["permissions"] == ["storage"]
    assert payload["host_permissions"] == ["https://github.com/*"]

    for name in ("content.js", "options.js"):
        source = (BROWSER / name).read_text(encoding="utf-8")
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "import("):
            assert forbidden not in source, f"{name} could reach the network via {forbidden}"


def test_the_browser_extension_is_manifest_v3() -> None:
    assert manifest(BROWSER / "manifest.json")["manifest_version"] == 3


def test_the_badge_is_drawn_beside_the_name_not_inside_the_readme() -> None:
    """The README is somebody else's content; editing it shows things the page does not say.

    Checked against what the script *selects*, not against whether the word
    appears -- the comment beside the selector says "not the README", and a
    substring hunt over a file that explains itself finds the explanation.
    """
    source = (BROWSER / "content.js").read_text(encoding="utf-8")
    # The quote character is back-referenced, because the selector is single
    # quoted and contains double quotes -- a naive character class stops at the
    # first inner quote and captures `[itemprop=`.
    selectors = [m.group("sel") for m in SELECTOR.finditer(source)]
    assert '[itemprop="name"]' in selectors
    assert not any("readme" in selector.lower() for selector in selectors)


def test_a_malformed_badge_is_refused_rather_than_rendered_empty() -> None:
    """An empty pill on a page the user does not control looks like a broken extension."""
    source = (BROWSER / "options.js").read_text(encoding="utf-8")
    assert "schemaVersion !== 1" in source


# ============================================================ JetBrains


def test_the_jetbrains_tools_parse_and_are_named() -> None:
    tools = ET.parse(JETBRAINS / "tools" / "DevRepro.xml").getroot().findall("tool")  # noqa: S314 -- our own file, in our own repository
    names = {t.get("name") for t in tools}
    assert "Scan this machine" in names
    assert "Agent readiness" in names


def test_every_jetbrains_tool_runs_devrepro_from_the_project_root() -> None:
    for tool in ET.parse(JETBRAINS / "tools" / "DevRepro.xml").getroot().findall("tool"):  # noqa: S314 -- our own file, in our own repository
        options = {o.get("name"): o.get("value") for o in tool.find("exec").findall("option")}
        assert options["COMMAND"] == "devrepro"
        assert options["WORKING_DIRECTORY"] == "$ProjectFileDir$"


def test_no_jetbrains_tool_synchronises_afterwards() -> None:
    """None of them writes a file, so a re-scan of the project is work for nothing."""
    for tool in ET.parse(JETBRAINS / "tools" / "DevRepro.xml").getroot().findall("tool"):  # noqa: S314 -- our own file, in our own repository
        assert tool.get("synchronizeAfterRun") == "false"


def _without_comments(source: str, suffix: str) -> str:
    """Source with its comments removed, so prose cannot fail a code check."""
    if suffix == ".xml":
        return re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    if suffix == ".json":
        # JSON has no comments; this project uses `"//"` keys for them.
        payload = json.loads(source)
        return json.dumps({k: v for k, v in payload.items() if not k.startswith("//")})
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


def _invocations(source: str, suffix: str) -> str:
    """Just the devrepro arguments a surface can actually run."""
    if suffix == ".xml":
        root = ET.fromstring(source)  # noqa: S314 -- our own file, in our own repository
        return " ".join(
            option.get("value") or ""
            for tool in root.findall("tool")
            for option in tool.find("exec").findall("option")
            if option.get("name") == "PARAMETERS"
        )
    # For JS and JSON, the argument arrays are the only place a subcommand can
    # appear as something that runs.
    return " ".join(re.findall(r"\[[^\[\]]*'[a-z-]+'[^\[\]]*\]", source))


# ============================================================== all three


@pytest.mark.parametrize(
    "path",
    [
        VSCODE / "extension.js",
        VSCODE / "package.json",
        BROWSER / "content.js",
        BROWSER / "options.js",
        JETBRAINS / "tools" / "DevRepro.xml",
    ],
)
def test_no_surface_offers_to_run_remediations(path: Path) -> None:
    """A menu item that runs `fix` is one click from running it by accident.

    The `--yes` gate exists so a person agrees each time, and an editor command
    is exactly the context where that agreement stops being deliberate.

    Checked against the *invocations*, not against the text: the JetBrains XML
    names `devrepro fix` in a comment explaining why it is absent, and a
    substring hunt cannot tell a promise from a breach.
    """
    source = path.read_text(encoding="utf-8")
    stripped = _without_comments(source, path.suffix)
    assert "fix" not in _invocations(stripped, path.suffix)


@pytest.mark.parametrize("folder", [VSCODE, BROWSER, JETBRAINS])
def test_every_surface_explains_itself(folder: Path) -> None:
    readme = folder / "README.md"
    assert readme.is_file()
    assert len(readme.read_text(encoding="utf-8")) > 400
