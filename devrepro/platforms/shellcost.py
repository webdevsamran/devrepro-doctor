"""What a shell profile does before it hands you a prompt.

Every new terminal, every `git` hook that spawns a login shell, every CI step
that runs `bash -lc`, pays for this file. A profile that has accumulated four
version managers costs somewhere between one and three seconds, and the tax is
invisible because nobody starts a shell and thinks about how long it took --
they think the machine is slow.

The expensive things are known and countable, and all of them are the same
shape: a subshell whose output is evaluated. `eval "$(pyenv init -)"` forks a
process, waits for it, and evaluates the result. `nvm.sh` is worse -- it is a
few thousand lines of shell, sourced, and it re-globs the versions directory.
`conda initialize` runs the interpreter. None of these is wrong, and four of
them together is the problem.

**This counts rather than measures.** Timing a shell startup means *starting a
shell*, which runs the user's own configuration -- arbitrary code, possibly
including things that prompt, connect or change state. That is not a read-only
diagnostic, and it is not worth it: the count and the classification say what to
remove, which is what a measurement would only have hinted at.

The profile text arrives already read and already redacted by the caller.
Nothing here opens a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "COSTLY_PATTERNS",
    "SLOW_STARTUP_THRESHOLD",
    "ProfileCost",
    "analyse_profile",
]

#: Above this many subshell-spawning initialisations, a shell start is
#: noticeable. Deliberately not a time budget: this counts, and a count is what
#: a person can act on line by line.
SLOW_STARTUP_THRESHOLD = 4

#: (pattern, label, why it costs). Each of these forks at least one process on
#: every single shell start.
COSTLY_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        r"""eval\s+["']?\$\(\s*pyenv\s+init""",
        "pyenv init",
        "forks pyenv and evaluates its output",
    ),
    (
        r"""eval\s+["']?\$\(\s*rbenv\s+init""",
        "rbenv init",
        "forks rbenv and evaluates its output",
    ),
    (
        r"""eval\s+["']?\$\(\s*nodenv\s+init""",
        "nodenv init",
        "forks nodenv and evaluates its output",
    ),
    (
        r"""eval\s+["']?\$\(\s*direnv\s+hook""",
        "direnv hook",
        "installs a hook that runs on every directory change",
    ),
    (
        r"""eval\s+["']?\$\(\s*mise\s+activate""",
        "mise activate",
        "forks mise and evaluates its output",
    ),
    (
        r"""eval\s+["']?\$\(\s*rye\b""",
        "rye shims",
        "forks rye and evaluates its output",
    ),
    (
        r"""eval\s+["']?\$\(\s*starship\s+init""",
        "starship init",
        "forks starship and evaluates its output",
    ),
    (
        r"""eval\s+["']?\$\(\s*zoxide\s+init""",
        "zoxide init",
        "forks zoxide and evaluates its output",
    ),
    (
        r"\bsource\b[^\n]*nvm\.sh|\bNVM_DIR\b[^\n]*nvm\.sh",
        "nvm.sh",
        "sources several thousand lines of shell and re-globs the versions directory",
    ),
    (
        r"__conda_setup=|conda\.sh|conda initialize",
        "conda initialize",
        "runs the Python interpreter before the prompt appears",
    ),
    (
        r"\bsource\b[^\n]*oh-my-zsh\.sh",
        "oh-my-zsh",
        "sources the framework and every enabled plugin",
    ),
    (
        r"\bsource\b[^\n]*(sdkman-init\.sh)",
        "sdkman",
        "sources SDKMAN's init script",
    ),
    (
        r"\bsource\b[^\n]*(asdf\.sh|asdf\.bash)",
        "asdf",
        "sources asdf and rebuilds its shim path",
    ),
)

#: Compiled once. The list is short and fixed, and recompiling per profile file
#: on every scan is the kind of waste `devrepro bench` exists to find.
_COMPILED: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(pattern, re.MULTILINE), label, why) for pattern, label, why in COSTLY_PATTERNS
)

#: Lines that are commented out cost nothing. Stripped before matching, because
#: a profile people have already pruned is full of these and reporting them
#: would make the finding wrong in the direction that destroys trust in it.
_COMMENT = re.compile(r"^\s*#.*$", re.MULTILINE)


@dataclass(frozen=True)
class ProfileCost:
    """What one profile file makes every new shell do."""

    path: str
    #: (label, why) for each initialisation found, in file order.
    initialisations: tuple[tuple[str, str], ...] = ()

    @property
    def count(self) -> int:
        return len(self.initialisations)

    @property
    def slow(self) -> bool:
        return self.count >= SLOW_STARTUP_THRESHOLD


def analyse_profile(path: str, text: str) -> ProfileCost:
    """Count the subshell-spawning initialisations in a profile.

    Order follows the file, because the advice is "look at these lines" and a
    reordered list makes the reader search.
    """
    body = _COMMENT.sub("", text or "")
    hits: list[tuple[int, str, str]] = []
    for pattern, label, why in _COMPILED:
        match = pattern.search(body)
        if match:
            # One entry per tool, not per occurrence: a profile that sources
            # nvm.sh twice has one problem, not two.
            hits.append((match.start(), label, why))
    hits.sort()
    return ProfileCost(path=path, initialisations=tuple((label, why) for _, label, why in hits))
