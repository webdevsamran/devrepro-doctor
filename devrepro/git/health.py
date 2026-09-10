"""Git repository health checks -- read-only, credential-safe.

The through-line is that git fails quietly. A clone with LFS content and no LFS
installed does not error: it writes pointer files, and the build fails later
complaining that a binary is corrupt. A sparse checkout does not error either;
the directory the build wants is simply absent. A shallow clone breaks
`git describe` and any diff against a base ref, with an error naming neither.
Each of those is a five-second check and an afternoon otherwise.

Capabilities:
- config health: autocrlf, hooks path, signing config presence, and
  credential-helper NAMES (never their stored values);
- credential-helper *reachability*: a helper configured but not installed means
  every fetch prompts or fails, and nothing says so until it does;
- Git LFS: installed, initialised, and whether this repository needs it;
- submodule readiness (declared vs initialized vs dirty);
- sparse checkout, shallow and partial clones -- the three ways a working tree
  can be legitimately incomplete;
- linked-worktree awareness so diagnostics don't misread worktrees as
  broken clones.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from devrepro.core.runner import CommandRunner, SubprocessRunner

__all__ = [
    "BUNDLED_CREDENTIAL_HELPERS",
    "CredentialHelper",
    "GitHealthReport",
    "SubmoduleStatus",
    "git_health",
]

#: Helpers git ships in its own exec directory rather than on PATH. A name that
#: is not one of these and does not resolve as `git-credential-<name>` is
#: configured but absent, which turns every authenticated fetch into a prompt
#: -- or, in CI, into a hang followed by a timeout.
BUNDLED_CREDENTIAL_HELPERS = frozenset(
    {"store", "cache", "netrc", "osxkeychain", "wincred", "libsecret", "gnome-keyring"}
)

_GIT_CONFIG_KEYS = (
    "core.autocrlf",
    "core.hookspath",
    "user.name",
    "user.email",
    "commit.gpgsign",
    "user.signingkey",
    "tag.gpgsign",
    "gpg.format",
)


@dataclass(frozen=True)
class CredentialHelper:
    """A configured helper, by name and scope. Never by value.

    `git config --show-origin` would give the scope for free and would also put
    the path of the user's global config -- which contains their username -- in
    the output. Asking each scope separately costs two more subprocess calls
    and keeps identity out of the report entirely.
    """

    name: str
    scope: str  # local | global | system
    resolvable: bool
    #: True for `store`, which writes credentials to `~/.git-credentials` in
    #: plain text. Reported as a fact, not read.
    plaintext: bool = False


@dataclass(frozen=True)
class SubmoduleStatus:
    path: str
    declared: bool
    initialized: bool
    dirty: bool | None  # None when not initialized


@dataclass(frozen=True)
class GitHealthReport:
    is_repo: bool
    is_linked_worktree: bool
    config: dict[str, str | None] = field(default_factory=dict)  # key -> value or None
    signing_configured: bool = False
    credential_helper_present: bool = False
    credential_helper_name: str | None = None  # name only, never config value
    lfs_available: bool = False
    lfs_version: str | None = None
    #: This repository declares LFS-tracked paths in a `.gitattributes`.
    lfs_required: bool = False
    #: `filter.lfs.smudge` is configured, i.e. `git lfs install` has been run
    #: for this user or repository. Installed and initialised are different
    #: states with the same symptom.
    lfs_initialised: bool = False
    submodules: tuple[SubmoduleStatus, ...] = ()
    #: The three legitimate ways a working tree can be incomplete.
    sparse_checkout: bool = False
    sparse_cone_mode: bool | None = None
    sparse_pattern_count: int | None = None
    shallow: bool = False
    partial_clone_filter: str | None = None
    credential_helpers: tuple[CredentialHelper, ...] = ()
    notes: tuple[str, ...] = ()


def _git(runner: CommandRunner, repo: Path, *args: str) -> str | None:
    res = runner.run(("git", *args), timeout=10.0, cwd=str(repo))
    if res.returncode != 0:
        return None
    return (res.stdout or "").strip() or None


#: How far to look for a `.gitattributes` declaring LFS-tracked paths. A
#: monorepo keeps them beside each package; going deeper costs a walk on every
#: scan for diminishing returns.
_MAX_ATTRIBUTES_DEPTH = 3


def _lfs_required(repo: Path) -> bool:
    """Does anything in this repository declare LFS-tracked paths?

    Read from `.gitattributes` rather than by asking `git lfs`, because the
    interesting case is precisely the one where `git lfs` is not installed.
    """
    for depth in range(_MAX_ATTRIBUTES_DEPTH + 1):
        pattern = "/".join(["*"] * depth + [".gitattributes"]) if depth else ".gitattributes"
        try:
            candidates = list(repo.glob(pattern))
        except OSError:  # pragma: no cover - defensive
            continue
        for path in candidates:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "filter=lfs" in text:
                return True
    return False


def _credential_helpers(
    runner: CommandRunner, repo: Path, exec_path: Path | None
) -> tuple[CredentialHelper, ...]:
    """Configured helpers per scope, with whether each one actually exists.

    A helper name that resolves to nothing is the failure this is for: `git
    config credential.helper manager` on a machine without Git Credential
    Manager means every authenticated fetch prompts, and in CI that is a hang
    followed by a timeout with no message naming the helper.
    """
    found: list[CredentialHelper] = []
    seen: set[tuple[str, str]] = set()
    for scope in ("local", "global", "system"):
        raw = _git(runner, repo, "config", f"--{scope}", "--get-all", "credential.helper")
        if not raw:
            continue
        for line in raw.splitlines():
            value = line.strip()
            if not value:
                continue
            # A helper may be configured as a shell fragment ("!f() { ... }")
            # or with arguments; the first token is the name.
            name = value.split()[0]
            if name.startswith("!"):
                # A custom command. It is reachable by definition -- git runs
                # it through the shell -- and its text is the user's, so it is
                # recorded as a name and nothing more.
                name = "custom"
                resolvable = True
            else:
                resolvable = _helper_resolves(name, exec_path)
            key = (name, scope)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                CredentialHelper(
                    name=name,
                    scope=scope,
                    resolvable=resolvable,
                    plaintext=name == "store",
                )
            )
    return tuple(found)


def _helper_resolves(name: str, exec_path: Path | None) -> bool:
    """Is `git-credential-<name>` actually present?

    Checked on disk rather than by running it. Some helpers block on stdin
    when invoked without input, and a diagnostic that hangs waiting for a
    credential prompt is worse than one that says nothing.
    """
    if name in BUNDLED_CREDENTIAL_HELPERS:
        return True
    binary = f"git-credential-{name}"
    if exec_path is not None:
        for suffix in ("", ".exe", ".cmd", ".bat"):
            if (exec_path / f"{binary}{suffix}").exists():
                return True
    from devrepro.probes.helpers import resolve_all_on_path

    return bool(resolve_all_on_path(binary))


def _submodules(repo: Path) -> tuple[SubmoduleStatus, ...]:
    gm = repo / ".gitmodules"
    if not gm.is_file():
        return ()
    parser = configparser.ConfigParser()
    try:
        parser.read(gm, encoding="utf-8")
    except (OSError, configparser.Error):
        return ()
    out: list[SubmoduleStatus] = []
    for section in parser.sections():
        if not section.startswith("submodule"):
            continue
        path = parser.get(section, "path", fallback=None)
        if not path:
            continue
        target = repo / path
        initialized = (target / ".git").exists() or (repo / ".git" / "modules" / path).exists()
        dirty: bool | None = None
        if initialized:
            # cheap dirtiness signal: .git dir present but no HEAD file readable
            head = target / ".git"
            dirty = not head.exists()
        out.append(
            SubmoduleStatus(
                path=path,
                declared=True,
                initialized=initialized,
                dirty=dirty,
            )
        )
    return tuple(out)


def git_health(root: Path | str, *, runner: CommandRunner | None = None) -> GitHealthReport:
    """Read-only Git health snapshot. Never prints credential values.

    ``runner`` is injectable so the whole report can be driven from recorded
    output; it used to construct a ``SubprocessRunner`` internally, which made
    every branch below reachable only on a machine that happened to be in the
    right state.
    """
    root = Path(root)
    runner = runner or SubprocessRunner()
    dot_git = root / ".git"
    is_repo = dot_git.exists()
    # a FILE named .git means a linked worktree, not a broken clone
    is_linked_worktree = dot_git.is_file()

    config: dict[str, str | None] = {}
    for key in _GIT_CONFIG_KEYS:
        config[key] = _git(runner, root, "config", "--get", key) if is_repo else None

    signing = any(config.get(k) for k in ("commit.gpgsign", "tag.gpgsign", "user.signingkey"))

    exec_path_raw = _git(runner, root, "--exec-path") if is_repo else None
    exec_path = Path(exec_path_raw) if exec_path_raw else None
    helpers = _credential_helpers(runner, root, exec_path) if is_repo else ()

    lfs_version = _git(runner, root, "lfs", "version")
    lfs_initialised = bool(_git(runner, root, "config", "--get", "filter.lfs.smudge"))

    sparse = (_git(runner, root, "config", "--get", "core.sparseCheckout") or "").lower() == "true"
    cone_raw = _git(runner, root, "config", "--get", "core.sparseCheckoutCone") if sparse else None
    pattern_count: int | None = None
    if sparse:
        sparse_file = dot_git / "info" / "sparse-checkout"
        try:
            lines = sparse_file.read_text(encoding="utf-8", errors="replace").splitlines()
            pattern_count = len([ln for ln in lines if ln.strip() and not ln.startswith("#")])
        except OSError:
            pattern_count = None

    shallow = (_git(runner, root, "rev-parse", "--is-shallow-repository") or "").lower() == "true"
    partial = _git(runner, root, "config", "--get", "remote.origin.partialclonefilter")

    notes: list[str] = []
    if is_repo and not is_linked_worktree and not (dot_git / "HEAD").exists():
        notes.append(".git exists but no HEAD; repository metadata may be incomplete")

    first_helper = helpers[0].name if helpers else None
    return GitHealthReport(
        is_repo=is_repo,
        is_linked_worktree=is_linked_worktree,
        config=config,
        signing_configured=signing,
        credential_helper_present=bool(helpers),
        credential_helper_name=first_helper,
        lfs_available=lfs_version is not None,
        lfs_version=lfs_version,
        lfs_required=_lfs_required(root),
        lfs_initialised=lfs_initialised,
        submodules=_submodules(root),
        sparse_checkout=sparse,
        sparse_cone_mode=(cone_raw or "").lower() == "true" if cone_raw is not None else None,
        sparse_pattern_count=pattern_count,
        shallow=shallow,
        partial_clone_filter=partial,
        credential_helpers=helpers,
        notes=tuple(notes),
    )
