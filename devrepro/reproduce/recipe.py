"""Turning "it fails on my machine" into something somebody else can run.

The README opens by promising to answer "Docker works there but not here", and
the honest end of that promise is not a diff -- it is a container somebody else
can start that fails the same way. A diff tells a maintainer what is different.
A reproduction tells them they are looking at the right thing.

The verb is `reproduce`, not `generate`. `generate` already means "draft a
config from what I detected", which is a different job with a different failure
mode, and reusing it would make two unrelated things share a name and a set of
flags.

**A recipe is emitted, never run.** Building the image is a side effect that
downloads gigabytes, and running the failing command is executing something the
project told us to execute. Both are the user's decision, and the recipe is the
artefact: reviewable, diffable, attachable to an issue, and runnable by the
person who chooses to.

Three properties decide whether a reproduction is worth anything:

**It pins.** A recipe that says `FROM python:3.12` reproduces a different thing
next month. The base image is resolved to a digest where the engine can resolve
it, and where it cannot, the file says so in a comment rather than pretending.

**It carries the assertion.** A reproduction that only sets up an environment
is a Dockerfile. What makes it a reproduction is that it ends by running the
thing that failed and expecting it to fail -- so that when somebody fixes the
cause, the recipe *stops* reproducing, which is the signal everybody actually
wants.

**It admits what it left out.** Local state that cannot cross a machine
boundary -- a database with data in it, a credential, a file outside the
repository -- is listed as an unmet precondition rather than silently omitted. A
recipe that fails for the wrong reason wastes more time than no recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from devrepro.core.models import ProjectRequirement, ScanReport

__all__ = [
    "BASE_IMAGES",
    "Precondition",
    "Reproduction",
    "SetupStep",
    "build_reproduction",
]

#: Ecosystem to a base image that already carries its runtime. Deliberately the
#: official images: a smaller base saves download time and costs an afternoon
#: the first time a native extension needs a compiler that is not there.
BASE_IMAGES: dict[str, str] = {
    "python": "python:{version}-bookworm",
    "node": "node:{version}-bookworm",
    "go": "golang:{version}-bookworm",
    "rust": "rust:{version}-bookworm",
    "java": "eclipse-temurin:{version}-jdk",
    "dotnet": "mcr.microsoft.com/dotnet/sdk:{version}",
    "ruby": "ruby:{version}-bookworm",
    "php": "php:{version}-cli-bookworm",
}

#: Fallback when the project declares nothing this recognises. Debian rather
#: than Alpine: musl changes how native extensions build, and a reproduction
#: that fails differently from the original is worse than none.
FALLBACK_IMAGE = "debian:bookworm-slim"

#: Ecosystem to the command that installs from its lockfile. The *locked*
#: install in every case -- `npm install` resolves fresh and would reproduce a
#: different dependency tree from the one that failed.
INSTALL_COMMANDS: dict[str, tuple[str, str]] = {
    # ecosystem: (lockfile, command)
    "npm": ("package-lock.json", "npm ci"),
    "pnpm": ("pnpm-lock.yaml", "pnpm install --frozen-lockfile"),
    "yarn": ("yarn.lock", "yarn install --immutable"),
    "poetry": ("poetry.lock", "poetry install --no-interaction"),
    "uv": ("uv.lock", "uv sync --frozen"),
    "pip": ("requirements.txt", "pip install --no-deps -r requirements.txt"),
    "cargo": ("Cargo.lock", "cargo fetch --locked"),
    "go": ("go.sum", "go mod download"),
    "bundler": ("Gemfile.lock", "bundle install --deployment"),
    "composer": ("composer.lock", "composer install --no-interaction"),
}


@dataclass(frozen=True)
class SetupStep:
    """One line of the recipe, and where it came from."""

    command: str
    reason: str
    #: The file that justified this step, when one did. A step nobody can trace
    #: back to a declaration is a step somebody will delete.
    source: str | None = None


@dataclass(frozen=True)
class Precondition:
    """Something the reproduction needs and cannot carry.

    Named rather than omitted. A recipe that fails because a database was empty
    wastes more of a maintainer's time than no recipe at all, because they
    debug the failure they were given instead of the one that was reported.
    """

    kind: str
    detail: str


@dataclass(frozen=True)
class Reproduction:
    """A recipe: a base, the steps, the failing command, and what is missing."""

    base_image: str
    #: The resolved digest, when the engine could resolve one. `None` means the
    #: recipe references a mutable tag and says so in its own comments.
    base_digest: str | None = None
    steps: tuple[SetupStep, ...] = ()
    #: The command that is expected to fail. Without it this is a Dockerfile.
    failing_command: str | None = None
    #: What failing looks like, so a reader can tell a successful reproduction
    #: from a different failure.
    expected_symptom: str | None = None
    preconditions: tuple[Precondition, ...] = ()
    platform: str = "linux"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def pinned(self) -> bool:
        return self.base_digest is not None

    @property
    def image_reference(self) -> str:
        return self.base_digest or self.base_image

    @property
    def reproduces(self) -> bool:
        """Whether this is a reproduction or merely an environment.

        The distinction is the whole point. An environment that sets things up
        and stops is a Dockerfile; a reproduction ends by running the thing
        that failed, so that fixing the cause makes the recipe stop working --
        which is the signal anybody actually wants from it.
        """
        return self.failing_command is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_image": self.base_image,
            "base_digest": self.base_digest,
            "pinned": self.pinned,
            "platform": self.platform,
            "steps": [
                {"command": s.command, "reason": s.reason, "source": s.source} for s in self.steps
            ],
            "failing_command": self.failing_command,
            "expected_symptom": self.expected_symptom,
            "preconditions": [{"kind": p.kind, "detail": p.detail} for p in self.preconditions],
            "reproduces": self.reproduces,
            "metadata": dict(self.metadata),
        }


def _base_for(requirements: tuple[ProjectRequirement, ...]) -> str:
    """The base image whose runtime the project actually declares.

    The *first* declared runtime wins rather than the most specific: a project
    declaring both Python and Node needs one of them in the base and the other
    installed, and picking the one the manifest mentions first matches what a
    person would have done.
    """
    for requirement in requirements:
        template = BASE_IMAGES.get(requirement.ecosystem)
        if template is None:
            continue
        version = _concrete_version(requirement.spec)
        if version is None:
            continue
        return template.format(version=version)
    return FALLBACK_IMAGE


def _concrete_version(spec: str) -> str | None:
    """A tag from a version range, or `None` when the range does not name one.

    `>=3.11` becomes `3.11`, which is a defensible reading: the floor is what
    the project promised to work on. `*` and `^1 || ^2` become `None`, and the
    recipe falls back rather than inventing a version the project never named.
    """
    import re

    if not spec or spec.strip() in {"*", "latest"}:
        return None
    if "||" in spec:
        return None
    match = re.search(r"(\d+(?:\.\d+)*)", spec)
    return match.group(1) if match else None


def _install_steps(
    requirements: tuple[ProjectRequirement, ...],
    present_lockfiles: frozenset[str],
) -> list[SetupStep]:
    """Locked installs for the ecosystems this project actually locked.

    Only where the lockfile is present. An `npm ci` in a repository with no
    `package-lock.json` fails on the first line of the build with an error
    about the lockfile, and a reproduction that never reaches the failing
    command reproduces nothing.
    """
    steps: list[SetupStep] = []
    seen: set[str] = set()
    ecosystems = {r.ecosystem for r in requirements}

    for ecosystem, (lockfile, command) in INSTALL_COMMANDS.items():
        if ecosystem in seen or lockfile not in present_lockfiles:
            continue
        # `pip` is claimed by any Python project; the rest need their own
        # ecosystem declared, so a stray `yarn.lock` in a subdirectory does not
        # add a yarn install to a pnpm project.
        if ecosystem not in ecosystems and not (ecosystem == "pip" and "python" in ecosystems):
            continue
        seen.add(ecosystem)
        steps.append(
            SetupStep(
                command=command,
                reason=(
                    f"Install from {lockfile}. The locked form, not the resolving one: "
                    "a fresh resolve reproduces a different dependency tree from the "
                    "one that failed."
                ),
                source=lockfile,
            )
        )
    return steps


def _preconditions(report: ScanReport) -> list[Precondition]:
    """What this recipe cannot carry across a machine boundary."""
    found: list[Precondition] = []

    if report.containers and report.containers.docker_daemon_ok:
        found.append(
            Precondition(
                kind="container-in-container",
                detail=(
                    "The original environment had a working container engine. If the "
                    "failure involves starting containers, this recipe cannot "
                    "reproduce it without a mounted socket -- which is a privilege "
                    "escalation, not a build step."
                ),
            )
        )

    if report.gpu and (report.gpu.nvidia_driver or report.gpu.rocm):
        found.append(
            Precondition(
                kind="gpu",
                detail=(
                    "The original environment had a GPU stack. A container reproduces "
                    "it only with the host's driver passed through, and the driver "
                    "version has to match."
                ),
            )
        )

    if report.platform.os_name.lower() != "linux":
        found.append(
            Precondition(
                kind="platform",
                detail=(
                    f"The failure was observed on {report.platform.os_name}. This "
                    "recipe runs Linux, so anything platform-specific -- path "
                    "separators, case sensitivity, line endings, the Windows path "
                    "limit -- will not reproduce here."
                ),
            )
        )

    return found


def build_reproduction(
    report: ScanReport,
    *,
    failing_command: str | None = None,
    expected_symptom: str | None = None,
    present_lockfiles: frozenset[str] = frozenset(),
    base_digest: str | None = None,
) -> Reproduction:
    """Assemble a recipe from a scan and the command that failed.

    `failing_command` is a parameter rather than something inferred. Guessing
    which command failed produces a recipe that runs the test suite when the
    problem was in the build, and a reproduction that reproduces the wrong
    thing is worse than an admission that we do not know.
    """
    requirements = report.requirements
    base = _base_for(requirements)

    steps: list[SetupStep] = [
        SetupStep(
            command="COPY . /work",
            reason="The repository as it stands. Nothing outside it travels.",
        )
    ]
    installs = _install_steps(requirements, present_lockfiles)
    steps.extend(installs)

    preconditions = _preconditions(report)
    if not installs and failing_command:
        # Without an install step the container has the runtime and none of the
        # project's dependencies, so the failing command will die with "not
        # found" -- a different failure, which is the most expensive kind of
        # wrong reproduction because it looks like a successful one.
        preconditions.insert(
            0,
            Precondition(
                kind="no-install-step",
                detail=(
                    "No lockfile this recipe understands was found, so nothing "
                    "installs the project's dependencies. The failing command will "
                    "most likely die with 'not found' rather than reproducing the "
                    "reported failure. Add the install step by hand before relying "
                    "on this."
                ),
            ),
        )

    return Reproduction(
        base_image=base,
        base_digest=base_digest,
        steps=tuple(steps),
        failing_command=failing_command,
        expected_symptom=expected_symptom,
        preconditions=tuple(preconditions),
        metadata={
            "devrepro_version": report.devrepro_version,
            "observed_on": f"{report.platform.os_name} {report.platform.arch}",
            "scanned_at": report.created_at.isoformat(),
        },
    )
