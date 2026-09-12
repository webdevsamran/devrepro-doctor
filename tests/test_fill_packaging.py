"""Filling a packaging manifest must not be a place to make something up.

`check_packaging.py` holds the committed templates to an all-or-nothing rule: a
manifest is either wholly placeholder or wholly real, because halfway is the
state that looks finished and fails on the day somebody first installs from it.
`fill_packaging.py` is the step that produces the "wholly real" half, and the
thing worth testing about it is that every value it writes came from a file
rather than from an argument.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _module(name: str) -> Any:
    path = _ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILL = _module("fill_packaging")
CHECK = _module("check_packaging")

VERSION = "1.2.3"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A `dist/` shaped like the one `python -m build` leaves behind."""
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / f"devrepro_doctor-{VERSION}.tar.gz").write_bytes(b"sdist bytes")
    (directory / f"devrepro_doctor-{VERSION}-py3-none-any.whl").write_bytes(b"wheel bytes")
    return directory


def test_the_digest_is_computed_from_the_file(dist: Path, tmp_path: Path) -> None:
    """The point of the whole script.

    A checksum passed in as an argument is a checksum nobody verified. Computing
    it means a manifest cannot claim a digest that does not belong to the
    artefact its URL points at.
    """
    out = tmp_path / "filled"
    assert FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)]) == 0

    formula = (out / "devrepro-doctor.rb").read_text(encoding="utf-8")
    expected = hashlib.sha256(b"sdist bytes").hexdigest()
    assert expected in formula


def test_the_wheel_and_the_sdist_do_not_get_each_other_s_digest(dist: Path, tmp_path: Path) -> None:
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])

    formula = (out / "devrepro-doctor.rb").read_text(encoding="utf-8")
    scoop = json.loads((out / "devrepro-doctor.json").read_text(encoding="utf-8"))

    assert hashlib.sha256(b"sdist bytes").hexdigest() in formula
    assert scoop["hash"] == hashlib.sha256(b"wheel bytes").hexdigest()
    assert scoop["hash"] not in formula


def test_no_placeholder_survives(dist: Path, tmp_path: Path) -> None:
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])
    for path in out.iterdir():
        leftover = re.findall(r"PLACEHOLDER_[A-Z0-9_]+", path.read_text(encoding="utf-8"))
        assert leftover == [], f"{path.name} still has {leftover}"


def test_the_result_satisfies_the_all_or_nothing_gate(dist: Path, tmp_path: Path) -> None:
    """The two scripts have to agree about what "finished" means.

    `check_packaging.py` accepts a manifest with no placeholders only when it
    carries a real https URL and a 64-character digest. Asserting that here
    keeps the producer and the gate from drifting into two different
    definitions.
    """
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])

    for path in out.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not CHECK.PLACEHOLDER.search(text)
        assert CHECK.REAL_URL.search(text), f"{path.name} has no https URL"
        assert CHECK.SHA256.search(text), f"{path.name} has no 64-hex digest"


def test_the_url_names_the_tag_for_that_version(dist: Path, tmp_path: Path) -> None:
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])
    scoop = json.loads((out / "devrepro-doctor.json").read_text(encoding="utf-8"))
    assert f"/download/v{VERSION}/" in scoop["url"]
    assert scoop["version"] == VERSION


def test_scoop_autoupdate_keeps_its_variable(dist: Path, tmp_path: Path) -> None:
    """`$version` is substituted by Scoop, not by this script.

    Freezing it to the current release would produce a manifest that installs
    the same version forever while claiming to auto-update.
    """
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])
    scoop = json.loads((out / "devrepro-doctor.json").read_text(encoding="utf-8"))
    assert "$version" in scoop["autoupdate"]["url"]
    assert VERSION not in scoop["autoupdate"]["url"]


def test_a_stale_artifact_from_another_version_is_not_picked_up(dist: Path, tmp_path: Path) -> None:
    """A `dist/` directory accumulates.

    Taking the first match would publish a manifest pointing at the previous
    release with a checksum that verifies -- correct-looking and wrong.
    """
    (dist / "devrepro_doctor-0.0.9.tar.gz").write_bytes(b"old")
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])
    formula = (out / "devrepro-doctor.rb").read_text(encoding="utf-8")
    assert "0.0.9" not in formula
    assert VERSION in formula


def test_two_artifacts_for_the_same_version_is_an_error(dist: Path, tmp_path: Path) -> None:
    (dist / f"devrepro_doctor-{VERSION}-py3-none-win_amd64.whl").write_bytes(b"other")
    with pytest.raises(SystemExit, match="more than one"):
        FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(tmp_path / "x")])


def test_a_missing_artifact_says_which_one(dist: Path, tmp_path: Path) -> None:
    (dist / f"devrepro_doctor-{VERSION}.tar.gz").unlink()
    with pytest.raises(SystemExit, match=r"no \.tar\.gz for version"):
        FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(tmp_path / "x")])


def test_winget_is_not_filled(dist: Path, tmp_path: Path) -> None:
    """It wants a signed Nullsoft installer; this project builds a wheel.

    Writing one anyway would mean inventing an `InstallerUrl`, which is exactly
    the halfway state the packaging gate exists to refuse.
    """
    out = tmp_path / "filled"
    FILL.main(["--version", VERSION, "--dist", str(dist), "--out", str(out)])
    assert not (out / "manifest.yaml").exists()
    assert "winget/manifest.yaml" not in FILL.FILLABLE


def test_the_committed_templates_are_still_templates() -> None:
    """This script writes to an output directory, never over `packaging/`.

    A real URL committed here would make the checked-in manifests assert a
    release that may not exist, and `check_packaging.py` would then hold them to
    it forever.
    """
    for relative in FILL.FILLABLE:
        text = (_ROOT / "packaging" / relative).read_text(encoding="utf-8")
        assert FILL.PLACEHOLDER.search(text), f"{relative} is no longer a template"
