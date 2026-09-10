"""What each rule id means, why it matters, and what to do about it.

A finding gives you a rule id and one line of summary. That is the right amount
for a table and not enough to act on, so this module is the long form: one
entry per rule, read by `devrepro explain` and published as a docs page.

Rule ids come in two shapes and both are covered:

* **Literal** -- written out in full at the emitting site, e.g.
  ``path/duplicates``.
* **Composed** -- assembled at runtime from a pack or tool name and a suffix,
  e.g. ``node/version-mismatch`` or ``python/multiple-installations``. The
  prefix is a value, so these are described once per suffix and resolved for
  any prefix.

Deliberately hand-written rather than scraped. A regex over the source finds
`application/json` and `actions/setup-node` too, and a catalogue that documents
MIME types as diagnostics is worse than no catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RuleDoc", "all_rule_docs", "explain_rule", "known_rule_ids"]


@dataclass(frozen=True)
class RuleDoc:
    """The long-form explanation of one rule."""

    rule_id: str
    title: str
    means: str
    matters: str
    fix: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "means": self.means,
            "matters": self.matters,
            "fix": self.fix,
        }


#: Suffixes the rule engine composes onto a pack or tool name.
_COMPOSED: dict[str, tuple[str, str, str, str]] = {
    "missing": (
        "Required tool not found",
        "The project declares this tool as a requirement and it does not resolve on PATH.",
        "Any command that needs it fails immediately, usually with a confusing "
        "'not recognized' or 'command not found' rather than a note about the "
        "declared requirement.",
        "Install it, or remove the requirement from the manifest if it is no "
        "longer real. Check `devrepro which <tool>` first -- the tool may be "
        "installed but shadowed or off PATH in this shell.",
    ),
    "cache-credential-committed": (
        "A build-cache credential is in a committed configuration file",
        "`nx.json`, `turbo.json` or `.bazelrc` sets a field that holds a "
        "remote-cache token or an Authorization header. The field's presence is "
        "reported; its value is never read.",
        "A read-write cache credential is a supply-chain secret: whoever holds "
        "it can write cache entries that every developer and every CI run then "
        "treats as trusted build output, without any of them fetching the "
        "source it supposedly came from. These files get committed without a "
        "second thought because they read like configuration rather than like "
        "secrets -- `.bazelrc` especially, which looks like a flags file.",
        "Move it to an environment variable, which all three tools read, and "
        "rotate it: it is in the git history whether or not you delete the line "
        "now.",
    ),
    "known-advisory": (
        "The installed tool version is covered by a published advisory",
        "The version of this build tool matches an entry in the offline "
        "advisory set that ships with devrepro, or in the bundle you supplied "
        "with `--db`.",
        "Dependency scanners never look at the compiler, the interpreter or "
        "git, because none of them appear in a lockfile. A toolchain can "
        "therefore sit years out of date behind a perfectly clean audit.",
        "Upgrade the tool to the fix on its own release branch -- backported "
        "fixes mean the highest version number is not always the answer. This "
        "comparison is offline and does not know whether your distribution "
        "backported the fix into the version string you have, which many do; "
        "check your distribution's changelog before treating it as urgent.",
    ),
    "version-ok": (
        "Version satisfies the requirement",
        "The installed version falls inside the range the project declares.",
        "Nothing to do. It is reported so a passing check is visible rather "
        "than inferred from silence.",
        "No action needed.",
    ),
    "version-mismatch": (
        "Version outside the declared range",
        "The tool is installed, but its version does not satisfy what the "
        "project's manifest requires.",
        "This is the most common cause of a build that works for one person "
        "and not another. Lockfiles, syntax features and native modules are all "
        "version-sensitive, and the failure usually surfaces far from the cause.",
        "Install a version inside the declared range, or widen the range if the "
        "declaration is stale. A version manager (mise, asdf, nvm, pyenv) makes "
        "this per-project rather than global.",
    ),
    "known-bad-version": (
        "Version explicitly forbidden by policy",
        "The installed version matches a range listed under "
        "`[known_bad_versions]` in the project's `.devrepro.toml`.",
        "Someone recorded that this exact version breaks the project. That is "
        "more specific than a range check and usually earned the hard way.",
        "Move off the forbidden version. The policy file should say why; if it "
        "does not, add the reason for whoever hits it next.",
    ),
    "version-unparseable": (
        "Version string could not be read",
        "The tool responded, but its version output did not match any pattern "
        "this project knows how to parse.",
        "The requirement cannot be checked either way, so this is reported as "
        "unknown rather than passing. A silent pass here would be a lie.",
        "Run the tool's version command by hand and open an issue with the "
        "output, so the parser can learn the shape.",
    ),
    "multiple-installations": (
        "Several copies of the same tool on PATH",
        "More than one executable with this name resolves on PATH. The first "
        "wins, and the others are reachable only by full path.",
        "The one that wins depends on PATH order, which differs between your "
        "shell, your editor's terminal, and CI. That is how the same command "
        "produces different versions in different windows on one machine.",
        "Run `devrepro which <tool>` to see every candidate and which one wins. "
        "Keep the installation you intend to use and remove or de-prefer the "
        "rest; `devrepro plan` proposes the PATH edit.",
    ),
    "shim-bypassed": (
        "A version manager is installed but not being used",
        "The manager's shim directory is on PATH, but another installation of "
        "this tool resolves before it.",
        "The manager still reports the version it intends -- `pyenv version` "
        "says 3.12 -- while every command gets something else, because "
        "resolution is decided by PATH order and nothing else. Neither tool is "
        "wrong about what it was asked, so nothing reports a problem, and the "
        "project's pinned version is quietly not in effect.",
        "Move the manager's shim directory earlier in PATH than the installation "
        "that currently wins. `devrepro which <tool>` lists every candidate in "
        "precedence order. Note that an IDE's integrated terminal often has a "
        "different PATH from a login shell, so check the one you actually build in.",
    ),
    "manager-conflict": (
        "Two version managers fighting over one ecosystem",
        "More than one version manager for this ecosystem initialises in your "
        "shell profiles -- for example both nvm and fnm, or both conda and "
        "pyenv.",
        "The last one to run wins, and which one that is depends on the order "
        "of lines in files you rarely read. The result is a tool version that "
        "changes when you open a different kind of terminal.",
        "Pick one manager per ecosystem and remove the other's init lines from "
        "your shell profile. `devrepro envmanagers` shows what is declared and "
        "what is active.",
    ),
}

_LITERAL: dict[str, tuple[str, str, str, str]] = {
    "git/lfs-required-not-installed": (
        "This repository needs Git LFS and it is not installed",
        "A `.gitattributes` here routes files through `filter=lfs`, and "
        "`git lfs` does not resolve on this machine.",
        "Git does not fail. It writes the pointer files -- a few lines of text "
        "where a binary should be -- reports the working tree as clean, and "
        "leaves the failure for whatever opens those files later. The error "
        "you get says the image is corrupt or the archive ended unexpectedly, "
        "and names a file rather than a missing tool.",
        "Install git-lfs, run `git lfs install`, then `git lfs pull` to replace "
        "the pointers already in your working tree. Cloning again without "
        "installing LFS first produces the same pointers.",
    ),
    "git/lfs-not-initialised": (
        "Git LFS is installed but its filters are not configured",
        "`git lfs` exists, but `filter.lfs.smudge` is unset for this user and "
        "repository, so the clean/smudge filters never run.",
        "Same symptom as not having LFS at all -- pointer files in the working "
        "tree, a clean `git status` -- and a different fix, which is why the "
        "two are separate findings rather than one. Being told to install "
        "something already installed is how a person concludes the tool is "
        "wrong and stops reading it.",
        "`git lfs install` configures the filters; `git lfs pull` fetches what "
        "the current checkout missed.",
    ),
    "git/lfs-ready": (
        "Git LFS is installed and configured for this checkout",
        "The repository declares LFS-tracked paths and the filters are in place.",
        "Recorded as a PASS because the absence of a finding and a verified "
        "match are different states, and a report that only lists problems "
        "cannot tell you which of the two it means.",
        "Nothing to do.",
    ),
    "git/submodules-uninitialised": (
        "Declared submodules have not been checked out",
        "`.gitmodules` names submodules whose directories are empty.",
        "An uninitialised submodule is an empty directory, not an error, so a "
        "build fails on a missing header or a missing module rather than on a "
        "missing submodule. `git status` says nothing, because as far as the "
        "outer repository is concerned nothing has changed.",
        "`git submodule update --init --recursive`. Adding "
        "`--recurse-submodules` to your clone avoids the state entirely.",
    ),
    "git/sparse-checkout-active": (
        "Sparse checkout is on, so parts of the tree are deliberately absent",
        "`core.sparseCheckout` is enabled and a pattern list decides which paths are materialised.",
        "This is normally deliberate and is reported rather than warned about. "
        "It earns a place because a build failing on a path that exists in the "
        "repository and not on disk has no other visible explanation -- "
        "`git status` is clean either way, and the file is present in every "
        "listing on the web.",
        "`git sparse-checkout list` shows what is included and "
        "`git sparse-checkout disable` restores the full tree. Nothing here "
        "needs changing if the narrowing was intended.",
    ),
    "git/shallow-clone": (
        "This is a shallow clone",
        "History before the graft point is absent, usually from a "
        "`--depth` clone or a CI checkout that defaults to depth 1.",
        "`git describe` produces the wrong version or fails, `git blame` stops "
        "at the graft, and any diff against a base ref -- including the one "
        "`devrepro guard --scope changed` uses -- cannot resolve the base. None "
        "of those errors mention shallowness.",
        "`git fetch --unshallow`. In GitHub Actions, `fetch-depth: 0` on the "
        "checkout step; most CI systems have an equivalent.",
    ),
    "git/partial-clone": (
        "This is a partial clone; some objects are fetched on demand",
        "A filter such as `blob:none` or `tree:0` is configured on the remote, "
        "so objects arrive lazily rather than at clone time.",
        "It is a deliberate and usually good trade. It matters here because an "
        "operation needing a missing blob reaches the network, and on an "
        "air-gapped or simply offline machine that failure reads as repository "
        "corruption rather than as a fetch that could not happen.",
        "Nothing, unless you work offline: `git fetch --refetch` with no filter "
        "materialises what is missing.",
    ),
    "git/credential-helper-missing": (
        "A credential helper is configured but not installed",
        "`credential.helper` names a helper that resolves to no program in "
        "git's exec directory or on PATH.",
        "Every authenticated fetch, clone and push falls back to prompting. "
        "Interactively that is a confusing password request for a repository "
        "you thought was public; in CI it is a hang followed by a timeout, and "
        "nothing in the output names the helper. The setting usually survives a "
        "machine migration or an OS change that the helper did not.",
        "Install the helper, or clear the setting with "
        "`git config --global --unset credential.helper`. devrepro reads the "
        "helper's name and never runs it -- several of them block on stdin.",
    ),
    "git/credential-store-plaintext": (
        "The `store` credential helper keeps tokens in plain text",
        "`credential.helper=store` writes credentials to `~/.git-credentials` unencrypted.",
        "Reported as information rather than a problem: on a single-user "
        "machine it is a considered choice, and it is the only helper that "
        "works everywhere. It is worth knowing because the file is readable by "
        "anything running as you -- including any package postinstall script -- "
        "and because backups and sync tools copy it without asking.",
        "An OS keychain helper (`osxkeychain`, `wincred`, `libsecret`) or Git "
        "Credential Manager stores the same tokens encrypted. devrepro reports "
        "the setting and never reads the file.",
    ),
    "dotnet/global-json-sdk-missing": (
        "global.json pins a .NET SDK that is not installed",
        "The repository's `global.json` requests an SDK version, and no "
        "installed SDK satisfies it under the file's `rollForward` policy.",
        '`dotnet build` fails with "A compatible .NET SDK was not found", '
        "while `dotnet --version` prints one of the SDKs that *is* installed "
        "and every other check passes -- which is why this reads as a working "
        "installation right up until the build. With `rollForward` unset the "
        "pin is exact to the feature band, so 8.0.100 and 8.0.404 are not "
        "interchangeable.",
        "Install the pinned SDK, or set `rollForward` in `global.json` if a "
        "newer one is genuinely acceptable. Deleting the pin works and gives "
        "up the reason it was added.",
    ),
    "dotnet/global-json-satisfied": (
        "An installed .NET SDK satisfies global.json",
        "One of the SDKs on this machine matches the pin under its `rollForward` policy.",
        "Recorded as a PASS because the absence of a finding and a verified "
        "match are different states, and a report that only lists problems "
        "cannot tell you which of the two it means.",
        "Nothing to do.",
    ),
    "dotnet/sdk-list-unavailable": (
        "The installed .NET SDKs could not be listed",
        "`global.json` pins an SDK, but `dotnet --list-sdks` did not answer.",
        "Whether the pin is satisfiable here is genuinely unknown, and "
        "reporting it as a blocker would be a guess. This is UNKNOWN rather "
        "than BLOCKED for that reason.",
        "Install the .NET SDK if this project is built on this machine. If it "
        "is not, nothing here needs changing.",
    ),
    "java/home-path-mismatch": (
        "JAVA_HOME and the java on PATH are different JDKs",
        "The JDK that `JAVA_HOME` points at reports a different version from "
        "the `java` the shell resolves.",
        "Maven and Gradle use `JAVA_HOME`; a shell script that calls `java` "
        "directly uses PATH. When they disagree, the build compiles against "
        "one JDK and runs on another, and the failure is an "
        "`UnsupportedClassVersionError` that names neither of them.",
        "Point `JAVA_HOME` at the JDK you intend to use and put its `bin` "
        "first on PATH. A toolchain block in the build file overrides both, so "
        "check that too if one is declared.",
    ),
    "java/multiple-jdks": (
        "Several JDKs are installed",
        "More than one JDK was found in the usual installation directories.",
        "Not a fault -- most Java developers need several. It is worth knowing "
        "because which one a build uses depends on `JAVA_HOME`, on PATH, and "
        "on whichever toolchain block the build file declares: three settings "
        "that are frequently out of step, and none of which announces itself.",
        "Nothing, unless a build behaves unexpectedly. `java -version` and "
        "`echo $JAVA_HOME` together tell you which two of the three agree.",
    ),
    "caches/compiler-cache-ineffective": (
        "The compiler cache is costing more than it saves",
        "`ccache` or `sccache` reports a hit rate low enough that the cache is "
        "adding work rather than removing it.",
        "Every miss pays a lookup, a write and an eviction on top of the "
        "compile it did not avoid. The usual cause is a cache smaller than the "
        "working set, so it evicts what it is about to need again. The symptom "
        'people report is "builds got slower after we turned caching on", '
        "which nobody attributes to the cache, and the numbers that would "
        "explain it are published by the cache itself and read by nothing.",
        "Raise the size limit -- `ccache --max-size` or `SCCACHE_CACHE_SIZE`. "
        "If the cache is not full, look for something that varies on every "
        "run: an absolute path, a timestamp or a build id in the compiler "
        "command line defeats caching entirely.",
    ),
    "caches/compiler-cache-effective": (
        "The compiler cache is earning its place",
        "The reported hit rate is high enough that the cache is saving more work than it costs.",
        "Recorded as a PASS because the absence of a finding and a verified "
        "measurement are different states, and a report that only lists "
        "problems cannot tell you which of the two it means.",
        "Nothing to do.",
    ),
    "caches/compiler-cache-full": (
        "The compiler cache is at its configured size limit",
        "Reported size has reached the maximum the cache was given.",
        "A cache at its ceiling evicts what it is about to need again, which "
        "is usually the *cause* of a low hit rate rather than a separate "
        "problem. It is reported alongside the rate because the rate is the "
        "symptom and this is the thing to change.",
        "Raise `max_size` (ccache) or `SCCACHE_CACHE_SIZE`. Both default to "
        "values chosen when repositories were smaller.",
    ),
    "caches/disk-low": (
        "Free disk space is low",
        "Less space remains than a cold dependency install or a container "
        "image pull typically needs.",
        "Enough for now, and not for the next `npm ci` or `docker pull`. The "
        'failure arrives mid-build as "no space left on device", from a step '
        "that has nothing to do with the cause.",
        "Build caches are usually the largest reclaimable thing on a "
        "developer machine. This scan lists the ones present rather than "
        "sizing them -- walking a Gradle cache costs more than the whole scan "
        "-- and each finding carries the command that measures it.",
    ),
    "caches/disk-critical": (
        "Free disk space is nearly exhausted",
        "So little space remains that ordinary operations will fail.",
        "A container build, a dependency install or even a git checkout will "
        "stop partway through, and the error will name whichever step "
        "happened to be running rather than the disk.",
        "Reclaim space before doing anything else. `docker system df` and the "
        "cache inventory in this report both name candidates; neither is "
        "pruned automatically, because which data is expendable is not "
        "something a diagnostic can know.",
    ),
    "caches/relocated": (
        "A build cache has been moved by an environment variable",
        "One or more caches are not in their default location, because a "
        "variable such as `PIP_CACHE_DIR` or `GRADLE_USER_HOME` points "
        "elsewhere.",
        "Usually deliberate and reported for one reason: a cache redirected "
        "onto a network share, an external volume, or a directory a cleanup "
        'job empties overnight is a common cause of "builds are slow on this '
        'machine only", with nothing in the build output that would explain '
        "it.",
        "Nothing, if the redirection was intended. If it was not, unset the "
        "variable; the default location is on the fastest disk the machine "
        "has, which is normally the point.",
    ),
    "abi/translated-process": (
        "This process runs under Rosetta translation",
        "The interpreter is an x86_64 build running on Apple silicon, with "
        "macOS translating every instruction.",
        "Nothing fails, which is the problem. Every package installed from "
        "here is the x86_64 build -- wheels, native addons, compiled "
        "extensions -- and they stay x86_64 for anything that loads them "
        "later. Builds take roughly ten times as long, and an extension "
        "compiled here will not load in a colleague's native arm64 process. "
        "The machine reports itself as arm64 throughout.",
        "Install an arm64 build of the runtime and re-create the virtualenv or "
        "`node_modules` from scratch. Reinstalling packages into the existing "
        "one keeps the x86_64 artefacts that are already there.",
    ),
    "abi/interpreter-arch-mismatch": (
        "The interpreter and the machine disagree about the architecture",
        "The process asking for packages reports one architecture while the host reports another.",
        "Package managers choose prebuilt artefacts by the *interpreter's* "
        "architecture, not the machine's, so everything installed through this "
        "interpreter is built for the wrong one. Installation succeeds every "
        "time; the cost appears as slow builds and as extensions that will not "
        "load elsewhere.",
        "Reinstall the runtime for this machine's architecture. A runtime "
        "carried across from an Intel Mac by a migration assistant is the "
        "usual cause, and it keeps working well enough to go unnoticed.",
    ),
    "abi/runtime-arch-mismatch": (
        "A runtime reports a different architecture from the machine",
        "`node`, `go` or a similar runtime answers with an architecture the host does not share.",
        "Prebuilt native addons are selected by the runtime's own "
        "architecture. A mismatch means every one of them is the emulated "
        "build, and any addon compiled here will not load in a native process "
        "-- which is how a `node_modules` directory becomes non-portable "
        "between two machines that look identical.",
        "Reinstall the runtime for this architecture and rebuild its native "
        "dependencies. For node, that is `npm rebuild` after removing "
        "`node_modules`.",
    ),
    "abi/musl-libc": (
        "This machine uses musl, so manylinux wheels will not load",
        "The C library is musl rather than glibc -- Alpine, and images derived "
        "from it, are the common case.",
        "A `manylinux` wheel is linked against glibc and cannot load here. pip "
        "does not report that: it skips the wheel and builds from source "
        "instead, which needs a compiler and development headers that a slim "
        "image deliberately does not carry. The error names a missing header "
        "file, and the actual cause -- the C library -- is never mentioned.",
        "Install the `musllinux` wheel where the project publishes one. Where "
        "it does not, add the build toolchain deliberately rather than "
        "discovering the need part-way through an install.",
    ),
    "abi/glibc-below-common-wheel-tag": (
        "glibc is older than the wheels most projects publish",
        "The installed glibc is below the floor required by the `manylinux` "
        "tag the ecosystem has largely moved to.",
        "Wheels carrying that tag are skipped silently and pip builds from "
        "source, which is how `pip install numpy` turns into a fifteen-minute "
        "compile that fails on a missing header. The finding names the tags "
        "this machine *can* install, because that is the part you can act on.",
        "Use a newer base image or distribution release. Pinning older "
        "releases of each package works and is a treadmill; the glibc floor "
        "only moves in one direction.",
    ),
    "abi/glibc-ok": (
        "glibc accepts the wheels most projects publish",
        "The installed glibc meets the floor for current `manylinux` tags.",
        "Recorded as a PASS because the absence of a finding and a verified "
        "match are different states, and a report that only lists problems "
        "cannot tell you which of the two it means.",
        "Nothing to do.",
    ),
    "containers/arch-emulated": (
        "The container engine is emulating another architecture",
        "The daemon reports a different CPU architecture from the host, so every "
        "build and every container runs through qemu.",
        "It works, which is why nobody notices. It is also roughly ten times "
        "slower, and the usual cause is a base image with no manifest for the "
        "host architecture -- so one line in a Dockerfile silently turns a "
        "one-minute build into a twenty-minute one.",
        "Use a base image that publishes your architecture, or pass `--platform` "
        "explicitly so the emulation is a decision rather than a surprise. If "
        "the target really is the other architecture, nothing here is wrong.",
    ),
    "containers/cgroup-v1": (
        "The container engine is using cgroup v1",
        "Resource limits are enforced through the first-generation cgroup "
        "interface rather than the unified hierarchy.",
        "Memory accounting differs between the two, so a container that is "
        "OOM-killed on a v2 CI runner can pass locally on v1 and the other way "
        "round. Swap accounting is often absent entirely under v1, which makes "
        "`--memory` mean something different from what the docs say.",
        "Enable unified cgroups on the host, or switch it on in Docker Desktop's "
        "settings. On a distribution still defaulting to v1, "
        "`systemd.unified_cgroup_hierarchy=1` on the kernel command line does it.",
    ),
    "containers/storage-driver-legacy": (
        "The storage driver is deprecated, removed, or has no copy-on-write",
        "The daemon is using a storage driver that current engines no longer "
        "recommend or no longer ship.",
        "`aufs` and `devicemapper` are removed in recent Docker releases, so an "
        "upgrade will stop the daemon starting. `vfs` is the one that surprises "
        "people: it is correct, it is what you get when nothing else is "
        "available, and it copies the entire filesystem for every layer.",
        "Move to overlay2. Changing the storage driver discards existing images "
        "and containers, so do it when you can afford to rebuild rather than "
        "in the middle of something.",
    ),
    "containers/disk-reclaimable": (
        "Container storage holds a large amount of reclaimable space",
        "The daemon's own accounting says a substantial share of its images, "
        "volumes and build cache is unreferenced.",
        "Running out of space mid-build produces one of the least informative "
        "errors in the ecosystem -- `no space left on device`, from a step that "
        "has nothing to do with the cause -- and it usually arrives with tens of "
        "gigabytes of dangling layers sitting behind it. Reporting it before it "
        "becomes that error is the only useful moment.",
        "`docker system prune -a --volumes` reclaims it. This tool does not run "
        "it and will not offer to: pruning deletes data, and which data is "
        "expendable is not something a diagnostic can know.",
    ),
    "containers/multiple-runtimes": (
        "More than one container engine is installed",
        "Two or more of Docker Desktop, Colima, Rancher Desktop, OrbStack, "
        "Podman, Lima and minikube resolve on PATH.",
        "This is not a fault -- plenty of people keep Colima beside Docker "
        "Desktop deliberately. It is worth knowing because it makes `docker "
        "context` load-bearing: a context pointing at a stopped VM produces "
        "exactly the error you would get with no daemon at all, and the "
        "obvious fix (start Docker Desktop) then changes nothing.",
        "`docker context ls` shows which engine `docker` currently talks to, "
        "and `docker context use <name>` switches it.",
    ),
    "containers/buildkit-unavailable": (
        "docker buildx is not available",
        "The daemon answers, but the buildx plugin is absent, so builds fall "
        "back to the legacy builder.",
        "Multi-platform builds, build secrets, cache mounts and `--mount=type="
        "cache` "
        "all require BuildKit. A Dockerfile using any of them fails with a "
        "syntax error rather than a message about the builder, which sends "
        "people looking in the wrong file.",
        "Install the buildx plugin from your package manager, or use a Docker "
        "distribution that bundles it. Nothing needs changing if no Dockerfile "
        "here uses BuildKit features.",
    ),
    "lockfiles/tool-too-old": (
        "The package manager is older than the lockfile format",
        "This lockfile is written in a format version that the installed package manager predates.",
        "The manager does not usually refuse. npm 6 handed a "
        "`lockfileVersion: 3` file rewrites the entire tree in the old format, "
        "and cargo before 1.78 cannot read a `version = 4` `Cargo.lock` at "
        "all. The first outcome is worse than the second: the install appears "
        "to succeed and the damage arrives as an unreviewable diff in someone "
        "else's pull request.",
        "Upgrade the package manager to the version the format requires. "
        "Downgrading the lockfile instead means every other machine that "
        "already has the newer manager re-upgrades it, and the file thrashes.",
    ),
    "lockfiles/manager-missing": (
        "A lockfile with no package manager to read it",
        "The repository contains a lockfile for a package manager that does not resolve on PATH.",
        "Nothing installs from it. This is a warning rather than a blocker "
        "because it is often correct: a project that moved from yarn to pnpm "
        "and left the old lockfile behind is untidy, not broken.",
        "Install the manager if the lockfile is current, or delete the "
        "lockfile if the project has moved on. Leaving both a `yarn.lock` and "
        "a `package-lock.json` in one directory means two machines can "
        "resolve two different dependency trees from the same commit.",
    ),
    "lockfiles/format-supported": (
        "The installed manager can use this lockfile",
        "The package manager on PATH is at or above the floor this lockfile format requires.",
        "Recorded as a PASS because the absence of a finding and a verified "
        "match are different states, and a report that only lists problems "
        "cannot tell you which of the two it means.",
        "Nothing to do.",
    ),
    "lockfiles/format-unknown": (
        "The manager is installed but did not report a version",
        "The package manager resolves on PATH, but asking it for its version "
        "produced nothing, so whether it can read the lockfile is unknown.",
        "Reported as UNKNOWN rather than folded into 'not installed', because "
        "the two have different fixes and conflating them sends you looking "
        "for a missing program that is right there. A common cause on Windows "
        "is a wrapper script resolving ahead of the real executable.",
        "Run the manager's `--version` by hand. If that works, the resolution "
        "order on PATH is the problem rather than the installation; "
        "`devrepro path` shows what resolves first.",
    ),
    "lockfiles/runtime-mismatch": (
        "The active runtime is outside the range this lockfile was solved for",
        "The lockfile records the runtime range it resolved against -- "
        "`requires-python`, `engines.node`, `RUBY VERSION` -- and the runtime "
        "on PATH falls outside it.",
        "A dependency graph is solved for a specific runtime range. Installing "
        "it on a runtime outside that range gives you packages whose own "
        "constraints were never checked against what you are running, and the "
        "failure appears at import or build time rather than at install time.",
        "Switch to a runtime inside the recorded range for this project, or "
        "re-resolve the lockfile on the runtime you intend to use and commit "
        "the result. Do not install across the boundary and hope.",
    ),
    "lockfiles/runtime-spec-unparseable": (
        "The lockfile pins a runtime range this tool cannot parse",
        "The recorded range uses ecosystem shorthand -- npm's `^20`, pip's "
        "`~=3.11` -- that this project's version comparison does not implement.",
        "Reported rather than skipped so the gap is visible. A tool that "
        "silently ignores a constraint it cannot read is indistinguishable "
        "from one that checked and found no problem.",
        "Check the range by hand against the runtime you are using. Comparator "
        "syntax (`>=20`, `>=3.11,<3.13`) is understood and can be used in "
        "`.devrepro.toml` if you want this enforced.",
    ),
    "lockfiles/unreadable": (
        "The lockfile could not be parsed",
        "The file exists but is not valid JSON, TOML or the text format its "
        "name implies -- usually a merge conflict left in place, or a "
        "truncated write.",
        "A lockfile that cannot be parsed cannot reproduce anything, and the "
        "error a package manager gives for one is rarely about the file.",
        "Regenerate it with its package manager rather than hand-editing. If "
        "the cause was a merge conflict, resolve the manifest first and then "
        "re-lock; resolving conflict markers inside a lockfile by hand "
        "produces a file that parses and is still wrong.",
    ),
    "hygiene/filesystem-case": (
        "Filesystem case sensitivity",
        "Whether this filesystem distinguishes `Config.py` from `config.py`.",
        "Linux is case-sensitive; Windows and macOS are not, by default. A "
        "repository authored on Linux that contains two files differing only in "
        "case loses one of them on checkout elsewhere, with no error at any "
        "point -- git reports success and the working tree is wrong.",
        "Nothing to change about the filesystem. Avoid committing paths that "
        "differ only in case; `git config core.ignorecase` affects how git "
        "compares them but not what the filesystem stores.",
    ),
    "hygiene/reserved-filename": (
        "A path uses a name Windows reserves",
        "The repository contains a path whose name is a DOS device name -- "
        "`con`, `prn`, `aux`, `nul`, `com1`-`com9` or `lpt1`-`lpt9` -- with or "
        "without an extension, so `aux.js` counts.",
        "Windows cannot create the file at all. The clone fails with an error "
        "that names neither the file nor the reason, and the repository is "
        "simply unusable there.",
        "Rename the path. This is reported on every platform on purpose: the "
        "person who can still fix it cheaply is the one about to commit it, not "
        "the one who cannot clone it.",
    ),
    "hygiene/symlinks-unavailable": (
        "This process cannot create symlinks",
        "On Windows, symlink creation needs Developer Mode or "
        "SeCreateSymbolicLinkPrivilege, and neither is available here.",
        "Git does not fail when it cannot create a symlink. It writes an "
        "ordinary file containing the link target instead, so the working tree "
        "differs from the commit while `git status` reports everything clean.",
        "Enable Developer Mode in Windows Settings, or work inside WSL where "
        "symlinks behave normally.",
    ),
    "hygiene/non-utf8-locale": (
        "Text encoding is not UTF-8",
        "The preferred encoding a subprocess inherits is a legacy codepage rather than UTF-8.",
        "Any tool that writes a non-ASCII character to this console can die "
        "with UnicodeEncodeError, and filenames with accents may not round-trip. "
        "This project hit exactly that: a single arrow in a remediation hint "
        "ended `devrepro check` on a cp1252 console.",
        "Set `PYTHONUTF8=1` for Python tools, or enable the OS-wide UTF-8 "
        "option (Windows: Region settings, 'Beta: Use Unicode UTF-8'). Note "
        "that the OS-wide switch affects every application, so it is worth "
        "changing deliberately rather than casually.",
    ),
    "path/duplicates": (
        "Duplicate PATH entries",
        "The same directory appears more than once in PATH.",
        "Every duplicate is searched again on every command lookup, so process "
        "startup gets slower for no benefit. It is also a sign that a profile "
        "is appending to PATH each time it is sourced.",
        "Remove the later occurrences, keeping the first. This never changes "
        "which executable wins, so it is a SAFE remediation.",
    ),
    "path/dead-entries": (
        "PATH entries that do not exist",
        "PATH lists directories that are not present on disk.",
        "The OS still stats every one of them on every lookup. On Windows in "
        "particular this measurably slows down each new process.",
        "Remove the entries. If one was supposed to exist, the tool that owns "
        "it probably failed to install.",
    ),
    "path/store-aliases": (
        "Windows Store execution aliases on PATH",
        "The `WindowsApps` alias directory is on PATH. It contains stub "
        "executables that open the Microsoft Store instead of running a tool.",
        "The stubs commonly shadow real installations -- the classic symptom is "
        "`python` opening the Store rather than the Python you installed.",
        "Settings > Apps > Advanced app settings > App execution aliases, and "
        "turn off the aliases for tools you have installed properly.",
    ),
    "python/store-alias-shadow": (
        "A Store alias is shadowing a real Python",
        "A `WindowsApps` python stub resolves before a genuine Python installation.",
        "`python` will not run the interpreter you installed. Virtualenv "
        "creation, pip and every script fail in ways that do not mention the "
        "alias.",
        "Disable the python app execution alias, or move the real "
        "installation's directory earlier in PATH.",
    ),
    "python/multiple-versions": (
        "Several Python versions installed",
        "More than one Python interpreter is present with differing versions.",
        "Not a problem in itself -- it is normal and often deliberate. It is "
        "reported because it is the context you need when a package installs "
        "into an interpreter other than the one you are running.",
        "No action needed unless a requirement is unmet. Use a per-project "
        "version manager or a virtualenv to make the choice explicit.",
    ),
    "containers/docker-daemon-unreachable": (
        "Docker CLI present, daemon not answering",
        "The `docker` command exists, but `docker info` cannot reach a daemon.",
        "Every container-based build, test and devcontainer fails until the "
        "daemon is running. The CLI being installed makes this look like a "
        "working setup when it is not.",
        "Start Docker Desktop, or `systemctl start docker` on Linux. On Windows "
        "check that the WSL backend is healthy.",
    ),
    "containers/docker-daemon-permission": (
        "Docker daemon refused this user",
        "The daemon is running, but this user is not permitted to talk to its socket.",
        "Every container command fails with a permission error that looks like "
        "the daemon is down. It is not: the daemon is fine and the user is not "
        "in the right group.",
        "On Linux, add your user to the `docker` group and start a new login "
        "session. Prefer that to running the CLI with sudo, which leaves "
        "root-owned files in your build outputs.",
    ),
    "containers/docker-daemon-pipe-missing": (
        "Docker Desktop's named pipe is absent",
        "The CLI tried to reach the daemon over its Windows named pipe and the "
        "pipe does not exist.",
        "This is what a stopped Docker Desktop looks like from the CLI's side. "
        "The message names the pipe rather than the application, so it reads "
        "like a configuration fault when it is simply not running.",
        "Start Docker Desktop and wait for it to report running, then re-run `devrepro doctor`.",
    ),
    # The doubled "docker-" is not a typo here: the probe composes
    # f"containers/docker-{kind}" and this kind is already
    # "docker-wsl-backend-error". Documented as emitted rather than as intended
    # -- rule ids reach SARIF and CI configs, so renaming one is a breaking
    # change that deserves its own decision, not a drive-by fix in a docs file.
    "containers/docker-docker-wsl-backend-error": (
        "Docker's WSL backend is unhealthy",
        "The daemon could not be reached and the error names WSL.",
        "Docker Desktop on Windows runs its engine inside WSL2. When that "
        "distribution is stopped, corrupt, or was updated underneath Docker, "
        "the CLI reports a connection failure that is really a WSL failure.",
        "Check `wsl --list --verbose` and `wsl --status`. Restarting WSL "
        "(`wsl --shutdown`, then start Docker Desktop) resolves most of these.",
    ),
    "containers/docker-daemon-error": (
        "Docker daemon returned an error this project does not classify",
        "`docker info` failed with a message that matched none of the known patterns.",
        "Reported verbatim rather than guessed at. A specific wrong diagnosis "
        "would send you further from the cause than an honest unknown.",
        "Read the evidence excerpt in the finding; it carries the daemon's own "
        "message. If the shape is common, it is worth a classifier branch.",
    ),
    "containers/docker-missing": (
        "Docker CLI not installed",
        "No `docker` executable resolves on PATH.",
        "Reported as INFO, not an error: plenty of projects never need it. It "
        "matters only when the project declares a container requirement.",
        "Install Docker only if this project needs it. `devrepro project` shows "
        "what is actually declared.",
    ),
    "containers/devcontainer-required": (
        "Policy requires a devcontainer definition",
        "The policy sets `require_devcontainer`, and no "
        "`.devcontainer/devcontainer.json` was found.",
        "The team decided one-command reproducible environments are the "
        "standard here, and this repository does not meet it.",
        "Run `devrepro generate devcontainer` for a reviewable draft, then adjust and commit it.",
    ),
    "containers/healthy": (
        "Container tooling is healthy",
        "The container runtime responded normally.",
        "Reported so a working container stack is visible in the report rather "
        "than inferred from the absence of an error.",
        "No action needed.",
    ),
    "containers/state-unknown": (
        "Container state could not be determined",
        "The probe could not establish whether container tooling works.",
        "Reported as unknown rather than healthy. A diagnostic that guesses is "
        "worse than one that admits the gap.",
        "Run `docker info` by hand to see what it says.",
    ),
    "cpp/no-compiler": (
        "No C/C++ compiler found",
        "No MSVC, gcc or clang resolves on PATH.",
        "Native extensions cannot build. This surfaces late and confusingly: "
        "`pip install` or `npm install` fails deep inside a build log rather "
        "than saying a compiler is missing.",
        "Install build tools for your platform -- Visual Studio Build Tools, "
        "Xcode Command Line Tools, or your distribution's build-essential.",
    ),
    "gpu/cuda-driver-old": (
        "Driver too old for the installed CUDA toolkit",
        "The NVIDIA driver version does not support the CUDA toolkit present.",
        "This is the specific incompatible pair, rather than the 'CUDA not "
        "found' that frameworks usually report. Training and inference either "
        "fail at load or silently fall back to CPU.",
        "Update the driver to one that supports the toolkit, or install a "
        "toolkit matching the driver.",
    ),
    "gpu/cuda-toolkit-missing": (
        "NVIDIA GPU present, CUDA toolkit absent",
        "A driver was detected but no CUDA toolkit was found.",
        "Frameworks fall back to CPU, usually without saying so clearly. The "
        "symptom is a job that runs but takes a hundred times longer.",
        "Install a CUDA toolkit compatible with the driver, or use a framework "
        "build that bundles its own runtime.",
    ),
    "gpu/no-accelerator": (
        "No GPU accelerator detected",
        "No NVIDIA, ROCm, oneAPI, Metal or DirectML stack was found.",
        "Informational. It matters only if the project expects acceleration.",
        "No action needed on a CPU-only machine.",
    ),
    "gpu/stack-detected": (
        "GPU/AI stack detected",
        "An accelerator stack was found and its versions recorded.",
        "Recorded so a snapshot diff can show when the stack changes -- one of "
        "the most common causes of a model that trains on one machine only.",
        "No action needed.",
    ),
    "gpu/state-unknown": (
        "GPU state could not be determined",
        "The probe could not establish what accelerator stack is present.",
        "Reported as unknown rather than absent.",
        "Run `nvidia-smi` or the equivalent for your vendor by hand.",
    ),
    "network/registry-override": (
        "Packages come from somewhere other than the public registry",
        "An `.npmrc`, `pip.conf`, `.cargo/config.toml` or similar points at a mirror or proxy.",
        "Normal on its own -- mirrors exist for good reasons. It matters when "
        "one machine has the override and another does not: the same install "
        "command then fetches different bytes, the lockfile still matches, and "
        "nothing reports a difference. A user-scoped override is the harder "
        "case, because it is invisible to everyone else on the team.",
        "Confirm the whole team shares the configuration, and prefer a "
        "project-scoped file over a user-scoped one so it is reviewable.",
    ),
    "network/ca-bundle-missing": (
        "A CA bundle variable points at a file that is not there",
        "`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE` or a sibling names a path "
        "that does not exist.",
        "The runtime falls back to its default trust store and the override "
        "does nothing, silently. Whoever set it believes the corporate CA is "
        "trusted, and it is not.",
        "Correct the path, or unset the variable so the fallback is deliberate "
        "rather than accidental.",
    ),
    "network/trust-store-partial": (
        "Some runtimes trust the corporate CA and others do not",
        "A custom CA bundle is configured for at least one ecosystem and not for others.",
        "Every runtime keeps its own trust store: Node reads "
        "`NODE_EXTRA_CA_CERTS`, Python `REQUESTS_CA_BUNDLE`, Go "
        "`SSL_CERT_FILE`, git `GIT_SSL_CAINFO`. Behind a TLS-intercepting "
        "proxy, configuring one means `npm install` works and `pip install` "
        "fails on the same machine, with an error that blames the certificate "
        "rather than the missing variable.",
        "Set the corresponding variable for each ecosystem you use. There is no "
        "single setting that covers them all, which is the whole difficulty.",
    ),
    "network/clock-skew": (
        "System clock is significantly wrong",
        "The system clock differs from network time by more than the tolerated margin.",
        "TLS certificate validation fails when the clock is far enough off, "
        "which breaks package installs, git over HTTPS and container pulls with "
        "errors that blame the certificate rather than the clock.",
        "Enable automatic time synchronisation for your OS.",
    ),
    "network/endpoint-unreachable": (
        "A development endpoint did not respond",
        "One of the checked registries or hosts was unreachable, or its TLS "
        "chain did not validate.",
        "Package installs will fail. Behind a corporate proxy this is usually "
        "TLS interception rather than an outage.",
        "Check proxy settings and whether your organisation's CA is trusted by "
        "the language runtime you are using -- Node, Python, Go and Java each "
        "keep their own trust store.",
    ),
    "network/endpoints-ok": (
        "Development endpoints reachable",
        "The checked registries responded with a valid TLS chain.",
        "Reported so a working network path is visible in the report.",
        "No action needed.",
    ),
    "ports/port-in-use": (
        "A declared port is already bound",
        "A port the project declares is in use by another process.",
        "The service will fail to start, usually with an 'address already in "
        "use' that does not say what is holding it.",
        "Stop the process holding the port, or change the port the project declares.",
    ),
    "env/required-names-present": (
        "Required environment variable names",
        "Whether the variable NAMES the policy requires are set. Values are "
        "never read, printed or stored.",
        "Missing configuration surfaces as a runtime failure far from the "
        "cause. Checking names catches it before the process starts.",
        "Set the missing variables in your shell profile or .env loader.",
    ),
    "env/credential-names-present": (
        "Credential-shaped variable names in this session",
        "Variables whose NAMES look like credentials exist in the environment. "
        "Their values are never read.",
        "Informational, and deliberately name-only: it tells you secrets are "
        "present in this shell without ever handling them.",
        "No action needed. It is context for anyone reading the report.",
    ),
    "shell/managers-initialized": (
        "Version managers initialised by shell profiles",
        "Which tool managers your shell profiles set up at startup.",
        "Context for PATH ordering and for `manager-conflict`.",
        "No action needed.",
    ),
    "system/os-detected": (
        "Operating system detected",
        "The OS, version and architecture this scan ran on.",
        "Every other finding is relative to this. It is also the first thing "
        "anyone comparing two machines wants.",
        "No action needed.",
    ),
    "system/resources": (
        "CPU, memory and disk headroom",
        "Totals only -- no serial numbers, no SMART data.",
        "Builds fail in confusing ways when a disk is nearly full, and a "
        "container build can exhaust one quietly.",
        "Free space if the report shows little headroom.",
    ),
    "system/shell": (
        "Active shell",
        "Which shell this scan believes you are running.",
        "Determines which profile files matter for PATH and manager initialisation.",
        "No action needed.",
    ),
    "virt/status": (
        "Virtualization capability",
        "Whether hardware virtualization and the relevant hypervisor are available.",
        "WSL2 and container backends need it. It is often disabled in firmware on new machines.",
        "Enable virtualization in firmware if a container backend needs it.",
    ),
    "wsl/detected": (
        "WSL is available",
        "WSL was found, with its distributions listed.",
        "Recorded because a Windows machine with WSL behaves very differently "
        "from one without, and the default distro determines which filesystem "
        "commands run against.",
        "No action needed.",
    ),
    "wsl/not-installed": (
        "WSL is not installed",
        "No WSL installation was detected on this Windows machine.",
        "Matters only if the project expects a Linux environment.",
        "`wsl --install` if the project needs it.",
    ),
    "wsl/no-default-distro": (
        "WSL has no default distribution",
        "WSL is installed but no distribution is set as default.",
        "`wsl <command>` fails, and tools that shell into WSL fail with it.",
        "`wsl --set-default <distro>`.",
    ),
    "sandbox/memory-parity": (
        "The sandbox gets far less memory than the machine it was tested on",
        "The container engine's ceiling, or a limit declared in compose or a "
        "devcontainer, is under a quarter of the host's memory.",
        "A build that links comfortably here can be killed in the sandbox with "
        "exit code 137 -- that is 128 plus SIGKILL, sent by the kernel's OOM "
        "killer, which writes nothing to the build log. It reads as a compiler "
        "crash, and the fix people reach for is a compiler flag.",
        "Raise the engine's memory limit (Docker Desktop: Settings > "
        "Resources), or lower the build's peak by pinning its parallelism. "
        "Plenty of containers are deliberately smaller than their host, so this "
        "is a difference worth knowing rather than an error.",
    ),
    "sandbox/cpu-parity": (
        "The sandbox gets fewer cores than the host, and build tools will not notice",
        "The effective core count inside the sandbox is below the host's.",
        "Build tools that detect parallelism through `nproc`, `os.cpu_count()` "
        "or an older JVM read the *host's* number and spawn that many workers "
        "into a smaller box. Nothing fails: the build thrashes and finishes "
        "several times slower, with no log line anywhere saying why.",
        "Pin the parallelism explicitly -- `make -j`, `cargo build -j`, "
        "`CARGO_BUILD_JOBS`, `MAKEFLAGS` -- rather than letting the tool detect "
        "it.",
    ),
    "sandbox/network-parity": (
        "The sandbox has no network and the build fetches dependencies",
        "A compose file or devcontainer disables the network, and this "
        "project's setup needs to reach a registry.",
        "No network is the correct default for an agent sandbox and the wrong "
        "one for a first build. Both declarations live in the same repository "
        "and neither knows about the other.",
        "Warm the dependency cache in an image layer, or vendor the "
        "dependencies, so the isolated run needs nothing from outside.",
    ),
    "buildtools/detected": (
        "A monorepo orchestrator is in use",
        "Nx, Turborepo, Bazel or a similar tool is configured in this "
        "repository, together with whether it uses a remote cache.",
        "Reported so that a cache is visible rather than assumed. A team that "
        "believes it has a shared cache and does not is wrong about why CI is "
        "slow, and a remote cache that is configured but unreachable costs "
        "more than none -- every task pays a lookup, fails it, and runs anyway.",
        "Nothing to fix. Read from configuration files only; no orchestrator "
        "is invoked, because `nx show projects` and `bazel info` both start a "
        "long-lived daemon.",
    ),
    "editor/style-conflict": (
        "The editor and the formatter have been told different things",
        "`.editorconfig` declares an indent style, width or line length that a "
        "configured formatter (prettier, ruff) contradicts.",
        "The editor formats one way as you type and the formatter rewrites it "
        "the other way on save or in a hook. The result is a whitespace diff "
        "nobody can attribute, on a two-line change, and the reviewer blames "
        "the author. Both tools are behaving exactly as configured, which is "
        "why nobody finds the cause.",
        "Pick one and make the other match. Whichever tool runs in CI is the "
        "one that decides, so `.editorconfig` should usually change to match "
        "the formatter rather than the reverse. Settings neither side has "
        "configured are not compared: a default is not a disagreement.",
    ),
    "kubectl/context-not-local": (
        "kubectl's current context may point at a production cluster",
        "The current kubeconfig context is not one of the local clusters this "
        "machine runs, and its name contains a marker like `prod` or `live`.",
        "The context is global to your user, persists across shells and "
        "reboots, and does not appear in a normal prompt. Every regretted "
        "`kubectl delete` was typed into a shell whose context the person "
        "believed was something else. This is blast radius, in the same sense "
        "`agent-check` uses the term.",
        "Confirm with `kubectl config current-context`, and consider a prompt "
        "segment that shows it. Note this is a guess from the context *name*: "
        "reading the cluster to be certain would mean an authenticated request "
        "to a production cluster from a diagnostic command, which is not a "
        "trade this tool makes.",
    ),
    "shell/slow-startup": (
        "A shell profile runs several subshell-spawning initialisations",
        "Four or more version managers or prompt tools initialise in a profile "
        "file, each forking at least one process before the prompt appears.",
        "Every new terminal pays this, and so does every git hook that spawns "
        "a login shell and every `bash -lc` in CI. Four of them together is "
        "one to three seconds, and nobody attributes it -- a shell that takes "
        "two seconds reads as a slow machine.",
        "Most of these support lazy initialisation: a shim that runs the real "
        "init the first time the tool is called, costing nothing until then. "
        "This is a count rather than a measurement, because timing a shell "
        "start means running your own configuration, which is not a read-only "
        "thing for a diagnostic to do.",
    ),
    "network/checks-skipped": (
        "Endpoint and TLS checks did not run, because they open connections",
        "A scan reports proxy configuration -- read from environment variables, "
        "which needs no connection -- and stops there. Reachability and TLS "
        "checks require opening sockets to github.com, the npm registry and "
        "PyPI, and a scan does not do that unless asked.",
        "Reported rather than left silent, because a scan that says nothing "
        "about network health reads as a scan that found network health fine. "
        "Until this was fixed, these checks ran on every scan: three "
        "third-party hosts, and any proxy in the path, learned that this "
        "machine had run this tool.",
        "Run `devrepro doctor --allow-network`, or `devrepro network "
        "--allow-network` for the fuller DNS, TLS and registry diagnostics.",
    ),
    "host/slow-filesystem": (
        "The project is on a filesystem where every file operation is slow",
        "The source tree sits on a WSL/Windows crossing, a network share or "
        "another mount where each file operation costs a millisecond instead of "
        "a microsecond.",
        "A dependency install performs hundreds of thousands of file "
        "operations. Three orders of magnitude on each is the difference "
        "between twenty seconds and twenty minutes -- and nothing is failing, so "
        "no profiler anybody runs will point at it. It reads as a slow build "
        "tool, which is where people go looking.",
        "Move the tree onto local storage. Inside WSL that means somewhere "
        "under ~, opened from the editor's WSL integration rather than through "
        "/mnt/c. On a network share, at minimum keep the dependency directory "
        "local -- most package managers accept a store or cache path outside "
        "the project.",
    ),
    "host/antivirus-scans-build-dirs": (
        "Real-time scanning inspects this project's build directories",
        "Windows Defender's real-time protection is on and its exclusion list "
        "does not cover the dependency and output directories this project "
        "actually has.",
        "Every file a build opens is scanned synchronously, on files written "
        "seconds earlier by a tool the machine already trusts. This is "
        "routinely the largest single factor in a Windows build taking several "
        "times longer than the same build elsewhere, and it is invisible: "
        "nothing fails and nothing logs.",
        "Excluding them is a trade, not a fix: it is a genuine reduction in "
        "protection on a tree whose install scripts execute code you did not "
        "write. Whether it is worth it depends on the machine and on your "
        "organisation's rules. DevRepro changes nothing -- the finding carries "
        "the exact command if you decide it is.",
    ),
    "host/antivirus-not-defender": (
        "Defender's real-time protection is off, so its exclusions mean nothing",
        "Defender answered and reported real-time protection disabled. On a "
        "machine that is not unprotected this usually means another antivirus "
        "product registered itself and Defender stood down.",
        "That other product's exclusion list is not visible from here, so this "
        "check cannot speak for whatever is actually scanning your build "
        "directories -- and scanning is a common cause of a Windows build being "
        "several times slower than the same build elsewhere.",
        "Nothing to fix here. If Windows builds are slow, check your antivirus "
        "product's own exclusion list for the project's dependency and output "
        "directories.",
    ),
    "host/antivirus-unknown": (
        "Defender's configuration could not be read from this shell",
        "`Get-MpComputerStatus` or `Get-MpPreference` did not answer. This is "
        "almost always a permissions result rather than an absent Defender.",
        "Reported rather than assumed, because from a non-elevated shell "
        "'could not read the exclusions' and 'there are no exclusions' look "
        "identical and lead to opposite conclusions.",
        "Run `devrepro doctor` from an elevated shell to see which build "
        "directories real-time scanning inspects.",
    ),
    "host/clock-unsynchronised": (
        "Nothing is correcting this machine's clock",
        "No time-synchronisation service is running, or the configured source "
        "is the machine's own hardware clock -- which is synchronising with "
        "itself and correcting nothing.",
        "The clock has not drifted yet; it will. When it does, the first "
        "symptom is usually a TLS error blaming a certificate that is fine "
        "('not yet valid', 'expired'), and somebody spends an afternoon on the "
        "certificate. It also breaks Kerberos outright and makes build tools "
        "rebuild -- or refuse to rebuild -- for reasons no log explains. This is "
        "the cause; clock skew is the symptom, detected separately and later.",
        "Windows: `w32tm /config /syncfromflags:domhier /update` on a domain "
        "machine, or point it at time.windows.com and start the Windows Time "
        "service. Linux: enable systemd-timesyncd or chrony.",
    ),
    "gpu/cuda-driver-too-old": (
        "The installed CUDA toolkit needs a newer driver than this one",
        "The CUDA toolkit's major version is ahead of the highest CUDA runtime "
        "the installed NVIDIA driver can run, as the driver itself reports it.",
        "Anything built with nvcc fails at launch with 'CUDA driver version is "
        "insufficient for CUDA runtime version', which names neither version. "
        "People reinstall the toolkit, or the driver, more or less at random.",
        "Update the NVIDIA driver, or install a toolkit inside the major "
        "version the driver supports. Note that CUDA 11+ guarantees minor-"
        "version compatibility, so 12.4 on a driver reporting 12.2 is fine and "
        "is not what this reports. To see what a framework build expects: "
        '`python -c "import torch; print(torch.version.cuda)"`.',
    ),
    "gpu/cuda-compatible": (
        "The CUDA toolkit and the driver agree",
        "The installed toolkit falls inside the major version the driver supports.",
        "Nothing to do. Reported so that a working CUDA setup is visible rather "
        "than inferred from the absence of a complaint.",
        "No action needed.",
    ),
    "gpu/cuda-toolkit-absent": (
        "A driver is present and nvcc is not",
        "`nvidia-smi` answered but no CUDA toolkit is on PATH, so the compiler "
        "half of the stack is unknown.",
        "Reported as information, not as a fault. A framework wheel ships its "
        "own CUDA runtime and never calls nvcc; the toolkit matters only if you "
        "compile CUDA code yourself.",
        "Install the CUDA toolkit only if you build CUDA sources. Otherwise nothing is missing.",
    ),
    "gpu/mixed-architectures": (
        "The GPUs in this machine have different compute capabilities",
        "Two or more devices report different `sm_XX` architectures.",
        "A build targeting one architecture produces kernels the other card "
        "cannot execute, and the failure -- 'no kernel image is available for "
        "execution on the device' -- names neither the device nor the "
        "architecture. It also arrives at runtime, on whichever device the "
        "scheduler happened to pick, so it looks intermittent.",
        "Build for every architecture present (TORCH_CUDA_ARCH_LIST or "
        "CMAKE_CUDA_ARCHITECTURES covering them all), or pin the job to one "
        "device with CUDA_VISIBLE_DEVICES.",
    ),
    "advisories/coverage": (
        "What the advisory set covers, and when it was reviewed",
        "Names the advisory data in use, the date it was last reviewed, and "
        "the tools it has any data for at all.",
        "An offline advisory set that is silent about a tool has given no "
        "answer, and silence reads as a clean result. Reporting coverage "
        "explicitly is the only thing that keeps those two apart. The date "
        "matters for the same reason: an old bundle is not a clean machine.",
        "Nothing to fix. To use a different or newer set, run `devrepro "
        "advisories --db <bundle.json>`; an external bundle needs a signature "
        "beside it and `DEVREPRO_ADVISORY_KEY` set.",
    ),
    "wsl/interop-disabled": (
        "WSL interop is disabled",
        "Windows/Linux interop is turned off in this WSL installation.",
        "Calling Windows executables from inside WSL fails, which breaks many "
        "cross-platform toolchains.",
        "Enable `interop` in `/etc/wsl.conf` and restart WSL.",
    ),
}


def _doc(rule_id: str, entry: tuple[str, str, str, str]) -> RuleDoc:
    title, means, matters, fix = entry
    return RuleDoc(rule_id=rule_id, title=title, means=means, matters=matters, fix=fix)


def explain_rule(rule_id: str) -> RuleDoc | None:
    """The long-form explanation for a rule id, or None if it is unknown.

    Literal ids are looked up directly. A composed id resolves by its suffix,
    so `node/version-mismatch` and `go/version-mismatch` share one explanation
    with the prefix carried through into the returned `rule_id`.
    """
    if rule_id in _LITERAL:
        return _doc(rule_id, _LITERAL[rule_id])
    _, _, suffix = rule_id.partition("/")
    if suffix and suffix in _COMPOSED:
        return _doc(rule_id, _COMPOSED[suffix])
    return None


#: Suffixes composed onto a *pack* name by `check_version_requirement`. Only
#: packs that actually call the version helpers can produce these -- `ai-gpu`
#: and `wsl` never do, so `ai-gpu/version-mismatch` is not a real id.
#: `tests/test_rule_catalog.py` holds this list against the pack sources.
VERSION_SUFFIXES = (
    "missing",
    "version-ok",
    "version-mismatch",
    "known-bad-version",
    "version-unparseable",
)

#: Packs whose modules call `runtime_findings` / `tool_findings` /
#: `check_version_requirement`, and so can emit the suffixes above.
VERSION_CHECKING_PACKS = (
    "containers",
    "cpp",
    "dotnet",
    "go",
    "java",
    "node",
    "python",
    "rust",
)

#: `f"{ecosystem}/manager-conflict"` in probes/shell_profiles.py, where the
#: ecosystem comes from a fixed map rather than the pack list.
MANAGER_CONFLICT_ECOSYSTEMS = ("python", "node")

#: `f"{name}/multiple-installations"` in probes/toolchains.py takes *any*
#: detected tool name, so its prefix domain is unbounded. These are the tools
#: this project probes for; the id is valid for any of them.
#: `f"{tool}/shim-bypassed"` in probes/toolchains.py: same unbounded prefix
#: domain as multiple-installations.
SHIM_BYPASS_EXAMPLES = ("python", "node", "ruby", "java")

#: `f"{name}/known-advisory"` in rules/packs/advisories.py. The prefix is
#: whichever tool the advisory set names, so the domain is exactly the set of
#: tools the bundled data covers -- narrow and enumerable, unlike the families
#: above. `tests/test_rule_catalog.py` holds it against the bundled data.
ADVISORY_TOOLS = ("git", "openssl", "python")

#: `f"{tool}/cache-credential-committed"` in probes/projecttools.py. The prefix
#: is the orchestrator's name, and the set of orchestrators this project reads
#: configuration for is fixed and short.
CACHE_CREDENTIAL_TOOLS = ("nx", "turborepo", "bazel")

MULTIPLE_INSTALL_EXAMPLES = (
    "python",
    "node",
    "npm",
    "git",
    "docker",
    "pip",
    "go",
    "java",
)


def known_rule_ids() -> list[str]:
    """Every id this project can emit, as far as it can be enumerated.

    Not a cross product. Each composed family has its own prefix domain, and
    `multiple-installations` accepts any detected tool name, so the entries
    listed for it are representative rather than exhaustive -- documented as
    such rather than presented as the complete set.
    """
    ids = set(_LITERAL)
    ids |= {f"{pack}/{suffix}" for pack in VERSION_CHECKING_PACKS for suffix in VERSION_SUFFIXES}
    ids |= {f"{eco}/manager-conflict" for eco in MANAGER_CONFLICT_ECOSYSTEMS}
    ids |= {f"{tool}/multiple-installations" for tool in MULTIPLE_INSTALL_EXAMPLES}
    ids |= {f"{tool}/shim-bypassed" for tool in SHIM_BYPASS_EXAMPLES}
    ids |= {f"{tool}/known-advisory" for tool in ADVISORY_TOOLS}
    ids |= {f"{tool}/cache-credential-committed" for tool in CACHE_CREDENTIAL_TOOLS}
    return sorted(ids)


def all_rule_docs() -> list[RuleDoc]:
    """The full catalogue, for `devrepro rules --catalog` and the docs page."""
    return [doc for rid in known_rule_ids() if (doc := explain_rule(rid)) is not None]
