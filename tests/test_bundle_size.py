"""The bundle budget has to fail on the regression it was written for.

A size gate is easy to write in a shape that only ever passes -- measure the
entry chunk, compare it to a number chosen to be comfortable, and never notice
that the number moved because the thing being measured stopped being the thing
that matters.

The regression this guards is specific and does not change the entry chunk's own
size much: somebody replaces one `lazy()` with a direct import, everything still
works, and Vite starts emitting a `modulepreload` for that route's chunk. The
route is now in the first paint. So the test that matters is the `modulepreload`
one below -- the rest exist so its failure can be trusted.
"""

from __future__ import annotations

import gzip
import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _module() -> Any:
    """Import scripts/check_bundle_size.py, which is not an importable package."""
    path = _ROOT / "scripts" / "check_bundle_size.py"
    spec = importlib.util.spec_from_file_location("check_bundle_size", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = _module()

#: Roughly what Vite emits: a module script, the stylesheet, and a preload hint.
INDEX = """<!doctype html>
<html lang="en">
  <head>
    <script type="module" crossorigin src="/assets/index-abc.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-def.css">
  </head>
  <body><div id="root"></div></body>
</html>
"""


def build(root: Path, html: str, assets: dict[str, bytes]) -> Path:
    """A dist directory shaped like the one Vite emits.

    Asset names are passed as strings rather than keyword arguments because they
    contain a dot, and a helper that rewrites `index_abc_js` into a filename
    gets it wrong in a way every assertion then quietly agrees with -- which is
    how the first version of this file passed while measuring nothing.
    """
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(html, encoding="utf-8")
    for name, payload in assets.items():
        (dist / "assets" / name).write_bytes(payload)
    return dist


def filler(size: int) -> bytes:
    """Bytes that do not compress away, so a KB asked for is a KB measured.

    Minified JavaScript compresses to roughly a third; random bytes compress to
    nothing at all. Using them means the numbers in these tests are the numbers
    the assertions are about, rather than the numbers after an entropy argument.
    """
    return os.urandom(size)


ENTRY = {"index-abc.js": filler(80_000), "index-def.css": b"x"}


def test_the_entry_script_and_stylesheet_are_the_initial_route() -> None:
    assert CHECK.entry_assets(INDEX) == ["/assets/index-abc.js", "/assets/index-def.css"]


def test_a_modulepreload_counts_toward_the_budget() -> None:
    """The regression this whole script exists for.

    Vite emits `modulepreload` for a chunk the entry imports eagerly. A route
    that stops being lazy appears here and nowhere else -- the entry chunk's own
    size barely moves.
    """
    html = INDEX.replace(
        "</head>",
        '<link rel="modulepreload" crossorigin href="/assets/fleet-xyz.js"></head>',
    )
    assert "/assets/fleet-xyz.js" in CHECK.entry_assets(html)


def test_a_prefetch_hint_does_not() -> None:
    """Explicitly the browser's idle-time work. Charging for it would punish a
    hint whose entire purpose is to cost nothing up front."""
    html = INDEX.replace("</head>", '<link rel="prefetch" href="/assets/later-xyz.js"></head>')
    assert "/assets/later-xyz.js" not in CHECK.entry_assets(html)


def test_an_unlazied_route_breaks_the_budget(tmp_path: Path, capsys: Any) -> None:
    """End to end, at the sizes this dashboard actually has.

    80 KB of entry is roughly where it sits today; the 40 KB preload is one
    route's chunk. Under budget before, over after, and nothing else changed.
    """
    html = INDEX.replace(
        "</head>",
        '<link rel="modulepreload" href="/assets/fleet-xyz.js"></head>',
    )
    before = build(tmp_path / "a", INDEX, ENTRY)
    assert CHECK.main(["--dist", str(before), "--budget", "100"]) == 0

    after = build(tmp_path / "b", html, {**ENTRY, "fleet-xyz.js": filler(40_000)})
    assert CHECK.main(["--dist", str(after), "--budget", "100"]) == 1
    assert "exceeds the 100 KB budget" in capsys.readouterr().err


def test_a_reference_the_build_did_not_emit_is_a_failure(tmp_path: Path, capsys: Any) -> None:
    dist = build(tmp_path, INDEX, {"index-def.css": b"x"})
    assert CHECK.main(["--dist", str(dist)]) == 1
    assert "which the build did not emit" in capsys.readouterr().err


def test_a_render_blocking_asset_from_another_origin_is_a_failure(
    tmp_path: Path, capsys: Any
) -> None:
    """It costs a connection and a round trip that this budget cannot see, which
    is worse than a large local file, not better."""
    html = INDEX.replace(
        "</head>",
        '<link rel="stylesheet" href="https://fonts.example/x.css"></head>',
    )
    dist = build(tmp_path, html, {"index-abc.js": b"x", "index-def.css": b"x"})
    assert CHECK.main(["--dist", str(dist)]) == 1
    assert "from another origin" in capsys.readouterr().err


def test_an_unbuilt_dashboard_says_so(tmp_path: Path, capsys: Any) -> None:
    assert CHECK.main(["--dist", str(tmp_path)]) == 1
    assert "npm run build" in capsys.readouterr().err


def test_the_measurement_does_not_drift(tmp_path: Path) -> None:
    """gzip stamps an mtime into its header. Without `mtime=0` the same bytes
    measure differently on different days, and a budget that flickers is a
    budget somebody turns off."""
    payload = filler(5_000)
    assert CHECK.gzipped(payload) == CHECK.gzipped(payload)
    # Bytes 4-7 of a gzip header are the timestamp. Zero means the archive is a
    # pure function of its input, which is what a budget needs it to be.
    assert gzip.compress(payload, compresslevel=9, mtime=0)[4:8] == bytes(4)


@pytest.mark.parametrize("budget", [1, 1000])
def test_the_budget_is_a_decision_not_a_constant(tmp_path: Path, budget: int) -> None:
    """`--budget` exists so raising it happens in a commit message somebody can
    read, rather than by editing a number nobody reviews."""
    dist = build(tmp_path, INDEX, {"index-abc.js": filler(50_000), "index-def.css": b"x"})
    assert CHECK.main(["--dist", str(dist), "--budget", str(budget)]) == (1 if budget == 1 else 0)
