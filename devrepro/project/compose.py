"""Policy inheritance: org → team → repo, and which layer said what.

A platform team publishes a paved road. A repository has its own needs. Today
those are the same file, so a repository either restates the org's rules -- and
they drift the moment the org changes one -- or ignores them, and the paved
road exists only in a wiki page nobody reads.

`extends` composes them. The mechanics are the easy half; the half that decides
whether anyone trusts the result is **attribution**. "node >=22" is not
actionable. "node >=22, required by the org paved road, which this repository
does not override" tells you who to argue with, and that is the difference
between a conformance report and a list of complaints.

Two deliberate constraints:

* **Local paths only.** An `extends` pointing at a URL would make loading a
  policy a network operation, and this tool does not touch the network unless
  a flag says to. A shared paved road belongs on disk -- vendored, submoduled,
  or synced by whatever already syncs it -- where it can be reviewed in a diff.
* **The nearest layer wins, and nothing merges silently within one key.** If
  the org says `node = ">=22"` and the repo says `node = ">=20"`, the repo wins
  and the report says the org was overridden. Intersecting the two ranges would
  be cleverer and would produce a requirement neither file contains, which
  nobody could then explain.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from devrepro.core.errors import PolicyError
from devrepro.core.models import Policy, PolicyRequiredEnvNames
from devrepro.project.policy import POLICY_FILENAME, _policy_from_toml

__all__ = [
    "MAX_POLICY_DEPTH",
    "ComposedPolicy",
    "PolicyLayer",
    "Provenance",
    "load_composed_policy",
]

#: How deep an `extends` chain may go. Org, team, repo is three; anything
#: substantially longer is a mistake or a loop, and a bounded depth turns both
#: into an error message rather than a hang.
MAX_POLICY_DEPTH = 8


@dataclass(frozen=True)
class PolicyLayer:
    """One file in the chain, and where it sat."""

    #: Repo-relative where possible, absolute otherwise. Layer paths are shown
    #: to the user, so they are the one place a path is legitimately useful --
    #: unlike a snapshot, a conformance report is read on the machine that
    #: produced it.
    path: str
    #: 0 is the file loaded directly; larger numbers are further up the chain.
    depth: int
    label: str


@dataclass(frozen=True)
class Provenance:
    """Which layer a single setting came from, and which layers it overrode."""

    key: str
    value: str
    layer: str
    overrides: tuple[str, ...] = ()

    @property
    def is_override(self) -> bool:
        return bool(self.overrides)


@dataclass(frozen=True)
class ComposedPolicy:
    """The merged policy, plus the paper trail that makes it arguable."""

    policy: Policy
    layers: tuple[PolicyLayer, ...] = ()
    provenance: tuple[Provenance, ...] = field(default_factory=tuple)

    def source_of(self, key: str) -> str | None:
        for entry in self.provenance:
            if entry.key == key:
                return entry.layer
        return None

    @property
    def overrides(self) -> tuple[Provenance, ...]:
        return tuple(p for p in self.provenance if p.is_override)


def _label_for(path: Path, depth: int) -> str:
    """A short name for a layer, so a report reads as prose.

    The file's own `[meta] name` wins when it has one, because a platform team
    naming its paved road is more useful than a filename. Failing that, the
    directory name -- `org/.devrepro.toml` reads as "org".
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    meta = data.get("meta")
    if isinstance(meta, dict):
        name = meta.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if depth == 0:
        return "this project"
    parent = path.parent.name
    return parent or path.name


def _extends_of(path: Path) -> list[Path]:
    """Resolve a layer's `extends`, relative to that layer's own directory.

    Relative to the *file*, not the working directory: a paved road referenced
    as `../org/paved-road.toml` has to mean the same thing regardless of where
    the command was run from, or a policy chain works from the repository root
    and breaks in a subdirectory.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"Invalid policy file {path}: {exc}") from exc

    raw = data.get("extends")
    if raw is None:
        return []
    entries = [raw] if isinstance(raw, str) else raw
    if not isinstance(entries, list):
        raise PolicyError("`extends` must be a path or a list of paths")

    resolved: list[Path] = []
    for entry in entries:
        if not isinstance(entry, str):
            raise PolicyError("every `extends` entry must be a string path")
        if "://" in entry:
            raise PolicyError(
                f"`extends` may not be a URL ({entry!r}).",
                hint="Loading a policy would become a network operation, and this "
                "tool does not use the network unless a flag says to. Vendor or "
                "sync the shared policy to a path instead.",
            )
        candidate = (path.parent / entry).resolve()
        if candidate.is_dir():
            candidate = candidate / POLICY_FILENAME
        if not candidate.is_file():
            raise PolicyError(
                f"{path.name} extends {entry!r}, which does not exist.",
                hint=f"Looked for {candidate}.",
            )
        resolved.append(candidate)
    return resolved


def _chain(start: Path) -> list[Path]:
    """The layer files, nearest first.

    Breadth-first so that with two parents the earlier `extends` entry is the
    nearer one -- which is what "listed first wins" means to someone reading
    the file.
    """
    ordered: list[Path] = []
    seen: set[Path] = set()
    frontier = [(start.resolve(), 0)]

    while frontier:
        current, depth = frontier.pop(0)
        if current in seen:
            # A cycle, or a diamond. Either way the first arrival is the
            # nearest one and re-adding it would change precedence.
            continue
        if depth >= MAX_POLICY_DEPTH:
            raise PolicyError(
                f"`extends` chain is deeper than {MAX_POLICY_DEPTH} layers.",
                hint="This is usually a loop. Org, team, repo is three.",
            )
        seen.add(current)
        ordered.append(current)
        frontier.extend((parent, depth + 1) for parent in _extends_of(current))

    return ordered


#: Policy fields that are dictionaries of `name -> value`, merged per key.
_MERGED_TABLES = ("required_runtimes", "required_tools", "optional_tools", "known_bad_versions")


def load_composed_policy(path: Path | None = None) -> ComposedPolicy:
    """Load a policy and everything it extends, nearest layer winning.

    Returns the merged `Policy` alongside a record of which layer supplied each
    setting and which layers it overrode -- without that, a developer told
    their machine is non-conformant has no way to find out whose rule they are
    failing.
    """
    target = path
    if target is None:
        cur = Path.cwd()
        for candidate in (cur, *cur.parents):
            found = candidate / POLICY_FILENAME
            if found.is_file():
                target = found
                break
    if target is None or not Path(target).is_file():
        raise PolicyError(
            f"No {POLICY_FILENAME} found.",
            hint="Create one in your project root; see README for the schema.",
        )

    files = _chain(Path(target))
    layers: list[PolicyLayer] = []
    parsed: list[tuple[str, Policy]] = []
    for depth, file in enumerate(files):
        label = _label_for(file, depth)
        layers.append(PolicyLayer(path=str(file), depth=depth, label=label))
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise PolicyError(f"Invalid policy file {file}: {exc}") from exc
        parsed.append((label, _policy_from_toml(data)))

    merged, provenance = _merge(parsed)
    return ComposedPolicy(policy=merged, layers=tuple(layers), provenance=tuple(provenance))


def _merge(parsed: list[tuple[str, Policy]]) -> tuple[Policy, list[Provenance]]:
    """Merge nearest-first, recording who was overridden.

    Iterating nearest-first means the first layer to mention a key owns it, and
    every later mention is something it overrode. Doing it furthest-first would
    give the same merged result and lose the trail.
    """
    if not parsed:  # pragma: no cover - the caller always has at least one
        return Policy(), []

    nearest = parsed[0][1]
    tables: dict[str, dict[str, object]] = {name: {} for name in _MERGED_TABLES}
    owner: dict[tuple[str, str], str] = {}
    overridden: dict[tuple[str, str], list[str]] = {}

    for label, policy in parsed:
        for table_name in _MERGED_TABLES:
            for key, value in getattr(policy, table_name).items():
                identity = (table_name, key)
                if identity in owner:
                    overridden.setdefault(identity, []).append(label)
                    continue
                owner[identity] = label
                tables[table_name][key] = value

    provenance = [
        Provenance(
            key=f"{table_name}.{key}",
            value=str(tables[table_name][key]),
            layer=owner[(table_name, key)],
            overrides=tuple(overridden.get((table_name, key), ())),
        )
        for table_name, key in sorted(owner)
    ]

    # Scalar sections are not merged key-by-key: `supported_os` is a statement
    # about the whole project, and a half-org half-repo answer would be one
    # neither file makes. The nearest layer that has one wins outright.
    merged = Policy(
        supported_os=nearest.supported_os,
        required_runtimes={k: str(v) for k, v in tables["required_runtimes"].items()},
        required_tools={k: str(v) for k, v in tables["required_tools"].items()},
        optional_tools={k: str(v) for k, v in tables["optional_tools"].items()},
        known_bad_versions={
            k: tuple(v) if isinstance(v, (list, tuple)) else (str(v),)
            for k, v in tables["known_bad_versions"].items()
        },
        containers=nearest.containers,
        required_env_names=_merge_env_names(parsed),
    )
    return merged, provenance


def _merge_env_names(parsed: list[tuple[str, Policy]]) -> PolicyRequiredEnvNames:
    """Required env names accumulate rather than override.

    A list of names is additive by nature: the org requiring `HTTP_PROXY` and
    the repo requiring `DATABASE_URL` means both are required. Letting the
    nearer layer replace the list would quietly drop the org's requirement, and
    nothing in the file says that is what a repository is doing.
    """
    names: list[str] = []
    for _label, policy in parsed:
        for name in policy.required_env_names.names:
            if name not in names:
                names.append(name)
    return PolicyRequiredEnvNames(names=tuple(names))
