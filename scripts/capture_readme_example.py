"""Regenerate the README's example scan output from the real renderer.

The README showed hand-written findings under the caption *"Real findings
you'll see (examples from actual scans)"*. Two things were wrong with it:

- the rule id `python/multiple-installations` does not exist. The real rule is
  `python/multiple-versions`. (Confusingly, `bun/multiple-installations` and
  friends *are* real -- those ids are generated per tool -- which is probably
  how the wrong one came to be written down.)
- the layout was a multi-line `Evidence:` / `Safe remediation:` block. The
  command prints a three-column Rich table and truncates summaries; the
  strings "Evidence:" and "Safe remediation" appear nowhere in the codebase as
  output text.

A live `devrepro doctor` cannot be committed as an example -- it reads
whichever machine runs it, so the output differs per developer and would churn
on every capture. So this feeds a fixture `ScanReport` through
`render_terminal_table`, the same function `devrepro doctor` calls, and prints
the same trailing line the command prints. The layout, the column widths and
the truncation all come from the program rather than from prose, and the rule
ids are checked against the ids the codebase can actually emit -- which is the
guard the README never had.

    python scripts/capture_readme_example.py            # rewrite the README
    python scripts/capture_readme_example.py --check    # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
sys.path.insert(0, str(ROOT))

if TYPE_CHECKING:
    from devrepro.core.models import ScanReport

MARK_OPEN = "<!-- capture:doctor -->"
MARK_CLOSE = "<!-- /capture:doctor -->"

#: (state, rule id, summary). Summaries follow the templates the emitting code
#: uses, with example values substituted -- see `devrepro/probes/path_env.py`,
#: `devrepro/rules/base.py`, `devrepro/rules/packs/containers.py` and
#: `devrepro/rules/packs/python.py`. Ordered deliberately *not* by severity, so
#: the capture also exercises the renderer's sort.
EXAMPLE_FINDINGS = (
    ("WARN", "path/duplicates", "7 duplicate PATH entries detected."),
    (
        "ERROR",
        "node/version-mismatch",
        "node 18.19.0 does not satisfy required range >=20.0.0.",
    ),
    (
        "BLOCKED",
        "containers/docker-daemon-unreachable",
        "Docker CLI 29.7.2 present but daemon unreachable. Connection refused.",
    ),
    (
        "WARN",
        "python/multiple-versions",
        "Multiple Python versions installed: 3.10.11, 3.11.9, 3.12.4. "
        "Active: 3.12.4 (official-installer).",
    ),
)

#: A rule id written out in full, e.g. "containers/docker-daemon-unreachable".
#: The separator class is `/` alone and the segment class excludes it, so each
#: repetition is anchored and cannot be split two ways. The first version used
#: `[/-]` as the separator while the segment class also contained `-`, which
#: made `-` ambiguous between the two and gave CodeQL a genuine `py/redos`:
#: exponential backtracking on input like `"0-` followed by many `--`. Real
#: rule ids always contain a `/`, so requiring one is also more accurate.
_LITERAL_ID = re.compile(r'"([a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)+)"')
_PACK_NAME = re.compile(r'pack="([a-z0-9-]+)"')
_COMPOSED_SUFFIX = re.compile(r'rule_id=f"\{rule_prefix\}/([a-z0-9-]+)"')


def emittable_rule_ids() -> set[str]:
    """Rule ids the code can produce, read statically out of the source.

    Two shapes have to be covered, which is why a plain substring search is
    not enough -- an earlier version of this guard rejected the real
    `node/version-mismatch`:

    - written out in full, either as `rule_id="python/multiple-versions"` or
      positionally, `self.finding("path/duplicates", ...)`;
    - composed, `rule_id=f"{rule_prefix}/version-mismatch"`, where
      `rule_prefix` is a pack's `pack=` argument, so every pack name crossed
      with every suffix is emittable.

    Being static it over-approximates a little (it pairs every pack with every
    suffix, and a few of those pairs are unreachable in practice). That is the
    safe direction for a guard whose job is to catch an id no code mentions at
    all, which is exactly what the README had.
    """
    blob = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "devrepro").rglob("*.py")
    )
    ids = set(_LITERAL_ID.findall(blob))
    packs = set(_PACK_NAME.findall(blob))
    suffixes = set(_COMPOSED_SUFFIX.findall(blob))
    ids |= {f"{pack}/{suffix}" for pack in packs for suffix in suffixes}
    return ids


def _assert_rules_exist() -> None:
    known = emittable_rule_ids()
    missing = [rule for _, rule, _ in EXAMPLE_FINDINGS if rule not in known]
    if missing:
        raise SystemExit(
            "the README example names rule ids that no code emits: " + ", ".join(missing)
        )


def _declared_version() -> str:
    """The version `pyproject.toml` declares.

    Deliberately *not* `devrepro.__version__`, which reports the version of the
    installed distribution. That is the right answer at runtime and the wrong
    one here: a stale editable install (mine said 0.1.0 while pyproject said
    0.2.0) would bake a different number into the README than CI renders, and
    `--check` would fail for a reason that has nothing to do with the README.
    The repo's declared version is the same everywhere the repo is.
    """
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _report() -> ScanReport:
    from devrepro.core.models import (
        Evidence,
        Finding,
        FindingState,
        PlatformInfo,
        ScanReport,
    )

    return ScanReport(
        devrepro_version=_declared_version(),
        platform=PlatformInfo(os_name="Windows", os_version="10.0.26200", arch="AMD64"),
        findings=tuple(
            Finding(
                rule_id=rule,
                state=FindingState(state),
                summary=summary,
                evidence=(Evidence(source="system", excerpt="README example fixture"),),
            )
            for state, rule, summary in EXAMPLE_FINDINGS
        ),
    )


def render() -> str:
    """Render the fixture through the code path `devrepro doctor` uses."""
    from devrepro.reports.renderers import render_terminal_table
    from rich.console import Console

    # Render into a StringIO rather than stdout: recording is what this needs,
    # and --check would otherwise dump the table on every CI run. (quiet=True
    # is not the answer -- it makes export_text() come back empty.)
    #
    # legacy_windows=False is load-bearing. Rich substitutes a lighter box
    # style when it thinks it is writing to a legacy Windows console, so the
    # same fixture came out as a square box here and a heavy box on the Linux
    # and macOS CI legs -- and --check failed on a README nobody had touched.
    # A capture whose output depends on where it ran is the same defect this
    # script exists to fix, one level up. Pinned to the box a UTF-8 terminal
    # produces, which is what a reader on GitHub sees.
    console = Console(
        file=io.StringIO(),
        width=100,
        no_color=True,
        record=True,
        legacy_windows=False,
    )
    console.print(render_terminal_table(_report()))
    # The command prints this after the table. The reproducibility-score line
    # that sits between them is omitted: a fixture that ran no probes has no
    # score, and inventing one here is the exact failure this script exists to
    # stop.
    console.print("Read-only scan. No data left this machine.")
    return "```console\n$ devrepro doctor\n" + console.export_text().rstrip() + "\n```"


def splice(text: str) -> str:
    if MARK_OPEN not in text or MARK_CLOSE not in text:
        raise SystemExit(f"README is missing the {MARK_OPEN} / {MARK_CLOSE} markers.")
    pattern = re.compile(re.escape(MARK_OPEN) + r".*?" + re.escape(MARK_CLOSE), re.S)
    return pattern.sub(lambda _: f"{MARK_OPEN}\n{render()}\n{MARK_CLOSE}", text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed README matches the renderer; exit 1 if not",
    )
    args = parser.parse_args()

    _assert_rules_exist()
    current = README.read_text(encoding="utf-8")
    updated = splice(current)

    if args.check:
        if current == updated:
            print("ok     README example matches what devrepro doctor renders")
            return 0
        print(
            "README example no longer matches what devrepro doctor renders.\n"
            "Run: python scripts/capture_readme_example.py",
            file=sys.stderr,
        )
        import difflib

        diff = difflib.unified_diff(
            current.splitlines(),
            updated.splitlines(),
            fromfile="README.md (committed)",
            tofile="README.md (rendered)",
            lineterm="",
        )
        for line in list(diff)[:60]:
            print(line, file=sys.stderr)
        return 1

    README.write_text(updated, encoding="utf-8", newline="\n")
    print("wrote  README.md (example rendered by the real code path)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
