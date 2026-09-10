"""A harness for rule-pack authors, and the four ways a rule pack is wrong.

`docs/PLUGINS.md` has always told authors to write a rule pack and use
`RecordingRunner`. It has never told them what a *correct* one looks like, so
every author has had to infer the contract from the built-in packs -- and the
things they infer wrong are always the same four:

**Findings with no evidence.** The model refuses to build one, so this surfaces
as an exception at scan time rather than at development time, in somebody
else's CI.

**Rule ids that collide with a built-in.** A pack emitting `python/missing`
makes `devrepro explain` describe somebody else's rule, and the user has no way
to tell which pack produced the finding.

**Packs that mutate.** A rule pack receives the machine's state and returns
findings. One that installs something, writes a file or opens a socket breaks
the guarantee the whole tool rests on, and nothing in the entry-point mechanism
stops it.

**Packs that raise.** The engine catches this and turns it into a
`rulepack/<name>/failed` finding, which is the right behaviour and means an
author never sees their own crash unless they look for it.

So the harness checks those four and reports them together. It is not a linter
for style and has no opinion about how a pack is written -- only about what a
pack must not do to the person running it.

`devrepro rules test <module>` drives this. Importing a module is executing it,
so the command says whose code it is about to run and takes the path as an
explicit argument rather than discovering packs and running them all.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from devrepro.core.models import Finding
    from devrepro.rules.base import RuleContext

__all__ = [
    "MUTATING_CALLS",
    "PackProblem",
    "PackReport",
    "check_pack",
    "check_pack_source",
]

#: Calls a rule pack has no business making. Matched against the source rather
#: than trapped at runtime, because a pack that only writes on a machine where
#: some condition holds would pass a runtime check on every other machine --
#: and the one it fails on is somebody's laptop.
MUTATING_CALLS: tuple[tuple[str, str], ...] = (
    ("subprocess", "A rule pack receives state; it does not run commands. Use ctx.runner."),
    ("os.system", "Same: the context carries a runner whose output is recorded and sanitized."),
    ("open", "Writing files breaks the read-only guarantee the whole tool rests on."),
    ("Path.write_text", "Writing files breaks the read-only guarantee."),
    ("Path.mkdir", "Creating directories is a side effect a scan must not have."),
    ("shutil", "Copying, moving and removing are all side effects."),
    ("socket", "A rule pack must not open a connection; network checks are opt-in elsewhere."),
    ("urllib.request", "Same: nothing in a scan reaches the network unless a flag asked."),
    ("requests", "Same, and it would add a dependency to every user of this pack."),
)


@dataclass(frozen=True)
class PackProblem:
    """One thing wrong with a rule pack, and what it does to the user."""

    kind: str
    detail: str
    where: str = ""

    def describe(self) -> str:
        return f"[{self.kind}] {self.detail}" + (f" ({self.where})" if self.where else "")


@dataclass(frozen=True)
class PackReport:
    """Everything the harness found, together."""

    findings_produced: int = 0
    problems: tuple[PackProblem, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "findings_produced": self.findings_produced,
            "problems": [
                {"kind": p.kind, "detail": p.detail, "where": p.where} for p in self.problems
            ],
        }


def check_pack_source(source: str, *, where: str = "") -> list[PackProblem]:
    """Static check for side effects a rule pack must not have.

    Read from the syntax tree rather than the raw text, so a mention in a
    docstring or a comment is not a finding -- the same distinction the
    Defender guarantee test had to make, and for the same reason: a module that
    explains why it does not do something would otherwise fail its own check.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [PackProblem("unparseable", f"the pack does not parse: {exc}", where)]

    problems: list[PackProblem] = []
    seen: set[str] = set()

    def flag(name: str, node: ast.AST) -> None:
        for marker, reason in MUTATING_CALLS:
            if (name == marker or name.startswith(marker + ".")) and marker not in seen:
                seen.add(marker)
                line = getattr(node, "lineno", 0)
                # `line 2` rather than a bare `2`: the location is printed in
                # parentheses after the message, where a lone number reads as
                # part of the sentence.
                location = f"{where}:{line}" if where else f"line {line}"
                problems.append(PackProblem("side-effect", f"{marker}: {reason}", location))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                flag(alias.name, node)
        elif isinstance(node, ast.ImportFrom) and node.module:
            flag(node.module, node)
        elif isinstance(node, ast.Call):
            flag(_call_name(node.func), node)

    return problems


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}".lstrip(".")
    return ""


def check_pack(
    evaluate: Callable[[RuleContext], Iterable[Finding]],
    ctx: RuleContext,
    *,
    reserved_prefixes: Iterable[str] = (),
) -> PackReport:
    """Run a pack against a context and report what it did wrong.

    The context comes from the caller so an author can test their pack against
    the machine shape it is written for. This never builds one: a harness that
    invented a plausible machine would test the pack against a fiction, and the
    interesting bugs in a rule pack are all about unusual state.
    """
    problems: list[PackProblem] = []

    source = ""
    try:
        source = inspect.getsource(inspect.getmodule(evaluate) or evaluate)
    except (OSError, TypeError):  # pragma: no cover - a pack defined in a REPL
        problems.append(
            PackProblem(
                "no-source",
                "The pack's source could not be read, so the side-effect check was "
                "skipped. That is not a pass.",
            )
        )
    if source:
        problems.extend(check_pack_source(source))

    try:
        findings = list(evaluate(ctx))
    except Exception as exc:
        # The engine turns this into a `rulepack/<name>/failed` finding, which
        # is right for a user and means an author never sees their own crash
        # unless something looks for it. This looks for it.
        problems.append(PackProblem("raised", f"{type(exc).__name__}: {exc}", "during evaluate()"))
        return PackReport(problems=tuple(problems))

    reserved = tuple(reserved_prefixes)
    for finding in findings:
        if not finding.evidence:
            # The model refuses to build one of these, so in practice this
            # arrives as a validation error at scan time -- in somebody else's
            # CI rather than in the author's editor.
            problems.append(PackProblem("no-evidence", f"{finding.rule_id} carries no evidence"))
        prefix = finding.rule_id.split("/", 1)[0]
        if prefix in reserved:
            problems.append(
                PackProblem(
                    "reserved-prefix",
                    f"{finding.rule_id} uses the built-in prefix {prefix!r}. "
                    "`devrepro explain` will describe somebody else's rule, and a user "
                    "cannot tell which pack produced the finding.",
                )
            )
        if "/" not in finding.rule_id:
            problems.append(
                PackProblem(
                    "malformed-id",
                    f"{finding.rule_id!r} is not `prefix/name`. Every other id in the "
                    "tool has that shape, and the catalogue resolves by suffix.",
                )
            )

    return PackReport(findings_produced=len(findings), problems=tuple(problems))
