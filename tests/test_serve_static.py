"""`devrepro serve` has to actually serve the console.

The command its own error state tells people to run -- *"Run `devrepro serve`
and open this page from the local server"* -- rendered a blank page, and had
done for as long as the fallback server existed. Nothing in this repository
imported `devrepro.cli.server`, so nothing could have noticed.

The cause is one conditional: every file that was not `.html` went out as
`application/octet-stream`, and a browser refuses to execute a module script
with that media type. Chrome says so in the console and renders nothing, which
reads as a broken app rather than a broken server.

That path is not an edge case. It is the dependency-free fallback, taken
whenever the optional FastAPI extra is not installed -- the default this project
advertises, on the platform it claims to support first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from devrepro.cli.server import CONTENT_TYPES, static_response

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A directory shaped like a Vite build."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (root / "assets" / "index-abc.js").write_text("export const x = 1", encoding="utf-8")
    (root / "assets" / "index-def.css").write_text(":root{}", encoding="utf-8")
    (root / "assets" / "index-abc.js.map").write_text("{}", encoding="utf-8")
    return root


def test_a_module_script_is_served_as_javascript(dist: Path) -> None:
    """The whole bug. `application/octet-stream` here is a blank page."""
    status, content_type, body = static_response(dist, "/assets/index-abc.js")
    assert status == 200
    assert content_type.startswith("text/javascript")
    assert b"export const x" in body


def test_the_stylesheet_is_served_as_css(dist: Path) -> None:
    # A stylesheet with the wrong type is dropped silently rather than loudly:
    # the page renders unstyled and nothing says why.
    _, content_type, _ = static_response(dist, "/assets/index-def.css")
    assert content_type.startswith("text/css")


def test_every_extension_a_vite_build_emits_has_a_type() -> None:
    for extension in (".html", ".js", ".css", ".json", ".svg", ".woff2", ".map", ".ico"):
        assert extension in CONTENT_TYPES, extension


def test_the_document_is_html(dist: Path) -> None:
    status, content_type, body = static_response(dist, "/")
    assert status == 200
    assert content_type.startswith("text/html")
    assert b"id=root" in body


def test_a_client_side_route_is_served_the_shell(dist: Path) -> None:
    """`/findings` is a route, not a file. The shell resolves it."""
    status, content_type, body = static_response(dist, "/findings")
    assert status == 200
    assert content_type.startswith("text/html")
    assert b"id=root" in body


def test_a_missing_asset_is_a_404_and_not_the_shell(dist: Path) -> None:
    """The second defect.

    Every miss fell back to `index.html` with a 200, so a mistyped asset URL
    answered a request for JavaScript with HTML -- and the browser's error was
    about a syntax error in the bundle, pointing at the wrong thing entirely.
    """
    status, content_type, _ = static_response(dist, "/assets/does-not-exist.js")
    assert status == 404
    assert not content_type.startswith("text/html")


def test_a_query_string_is_not_part_of_the_file_name(dist: Path) -> None:
    """A cache-buster made the file unfindable, and the fallback hid it."""
    status, content_type, _ = static_response(dist, "/assets/index-abc.js?v=2")
    assert status == 200
    assert content_type.startswith("text/javascript")


@pytest.mark.parametrize(
    "attack",
    [
        "/../secret.txt",
        "/assets/../../secret.txt",
        "/%2e%2e/secret.txt",
        "/....//secret.txt",
    ],
)
def test_nothing_outside_the_built_console_is_served(dist: Path, attack: str) -> None:
    """The third defect, and the one that matters most for this project.

    The request path was joined to the directory without resolving it. A browser
    normalises `..` away before sending, but this server does not only talk to
    browsers -- and it runs on a machine whose entire selling point is that its
    diagnostics never leave it.
    """
    (dist.parent / "secret.txt").write_text("not yours", encoding="utf-8")
    status, _, body = static_response(dist, attack)
    assert status == 404
    assert b"not yours" not in body


def test_an_unbuilt_console_is_a_404_rather_than_a_crash(tmp_path: Path) -> None:
    status, _, _ = static_response(tmp_path / "never-built", "/index.html")
    assert status == 404


def test_an_unknown_extension_is_never_guessed_as_html(dist: Path) -> None:
    """Guessing HTML for an unknown file is how a 404 becomes a blank 200."""
    (dist / "weird.xyz").write_text("?", encoding="utf-8")
    _, content_type, _ = static_response(dist, "/weird.xyz")
    assert content_type == "application/octet-stream"
