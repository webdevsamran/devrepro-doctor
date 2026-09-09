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
    return sorted(ids)


def all_rule_docs() -> list[RuleDoc]:
    """The full catalogue, for `devrepro rules --catalog` and the docs page."""
    return [doc for rid in known_rule_ids() if (doc := explain_rule(rid)) is not None]
