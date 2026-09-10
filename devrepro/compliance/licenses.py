"""What the *toolchain* is licensed under, and why that is usually a non-issue.

Every license scanner in circulation walks the dependency tree, because that is
where the obligations are. Nobody inventories the compiler. Then legal asks
"you told us there is no GPL in this product, but you build it with GCC" and
the answer takes a week to assemble because nothing recorded which compiler it
even was.

The answer is short and this module states it plainly rather than burying it in
a table: **compiling a program with a tool does not put you under that tool's
license.** GCC ships a Runtime Library Exception for exactly this, and every
mainstream toolchain either has an equivalent or is permissively licensed to
begin with. The obligation that does exist is narrower -- linking a runtime
library, or *redistributing the toolchain itself*, which is what a container
image does.

So the inventory reports two separate things: the license, and whether using
the tool as a build tool creates an obligation. Reporting the first without the
second is what makes toolchain license reports frightening and useless.

Unknown is a real answer. A tool absent from the table gets `None`, not a
plausible guess. A license inventory whose entries were inferred is not an
inventory, and the person reading it has no way to tell which rows were which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from devrepro.core.models import ScanReport

__all__ = [
    "TOOL_LICENSES",
    "BuildObligation",
    "ToolLicense",
    "license_for",
    "toolchain_licenses",
]

#: What using the tool *as a build tool* obliges you to do.
#:
#: - `none`: permissive, or an explicit exception covers the output.
#: - `redistribution-only`: no obligation from building, but shipping the tool
#:   itself (in a container image, say) carries the license with it.
#: - `review`: the tool's runtime can end up linked into the output, so the
#:   answer depends on how it was used and a person has to look.
BuildObligation = Literal["none", "redistribution-only", "review"]


@dataclass(frozen=True)
class ToolLicense:
    """One toolchain component's license, and what it actually requires."""

    tool: str
    spdx: str
    obligation: BuildObligation
    #: Why the obligation is what it is. The table is worthless without this:
    #: "GPL-3.0-or-later" next to a compiler reads as an alarm, and the
    #: sentence next to it is the reason it is not one.
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "spdx": self.spdx,
            "obligation": self.obligation,
            "note": self.note,
        }


#: Licenses for the toolchain components this project identifies. Keyed by the
#: same names the probes emit, so a row here always corresponds to something
#: that can actually appear in a report.
TOOL_LICENSES: dict[str, ToolLicense] = {
    entry.tool: entry
    for entry in (
        ToolLicense(
            "gcc",
            "GPL-3.0-or-later WITH GCC-exception-3.1",
            "none",
            "The Runtime Library Exception exists so that compiling with GCC "
            "does not place the output under the GPL. Redistributing GCC "
            "itself still does.",
        ),
        ToolLicense(
            "clang",
            "Apache-2.0 WITH LLVM-exception",
            "none",
            "Permissive, with an exception that covers runtime library code "
            "linked into the output.",
        ),
        ToolLicense(
            "rustc",
            "MIT OR Apache-2.0",
            "none",
            "Dual-licensed permissively; the standard library ships under the same terms.",
        ),
        ToolLicense("cargo", "MIT OR Apache-2.0", "none", "Same terms as the Rust toolchain."),
        ToolLicense(
            "go",
            "BSD-3-Clause",
            "none",
            "Permissive. The standard library is linked into every Go binary "
            "and the license permits it with attribution.",
        ),
        ToolLicense(
            "python",
            "PSF-2.0",
            "none",
            "Permissive. Bundling the interpreter requires including its license text.",
        ),
        ToolLicense("node", "MIT", "none", "Permissive; bundled OpenSSL carries its own terms."),
        ToolLicense("npm", "Artistic-2.0", "none", "Permissive."),
        ToolLicense("pnpm", "MIT", "none", "Permissive."),
        ToolLicense("yarn", "BSD-2-Clause", "none", "Permissive."),
        ToolLicense("bun", "MIT", "none", "Permissive."),
        ToolLicense("pip", "MIT", "none", "Permissive."),
        ToolLicense("uv", "MIT OR Apache-2.0", "none", "Permissive."),
        ToolLicense("poetry", "MIT", "none", "Permissive."),
        ToolLicense(
            "git",
            "GPL-2.0-only",
            "redistribution-only",
            "Using git creates no obligation on your source. Shipping git "
            "inside an image you distribute does.",
        ),
        ToolLicense(
            "make",
            "GPL-3.0-or-later",
            "redistribution-only",
            "A build driver; it contributes nothing to the output.",
        ),
        ToolLicense("cmake", "BSD-3-Clause", "none", "Permissive."),
        ToolLicense(
            "docker",
            "Apache-2.0",
            "redistribution-only",
            "The engine is permissively licensed; images you build carry the "
            "licenses of whatever is inside them, which is the question that "
            "actually matters.",
        ),
        ToolLicense("podman", "Apache-2.0", "none", "Permissive."),
        ToolLicense("kubectl", "Apache-2.0", "none", "Permissive."),
        ToolLicense(
            "java",
            "GPL-2.0-only WITH Classpath-exception-2.0",
            "review",
            "Depends on the distribution: an OpenJDK build carries the "
            "Classpath Exception, and an Oracle JDK is under a separate "
            "commercial agreement with its own field-of-use terms.",
        ),
        ToolLicense("dotnet", "MIT", "none", "The SDK and runtime are permissive."),
        ToolLicense("ruby", "Ruby OR BSD-2-Clause", "none", "Permissive."),
        ToolLicense("php", "PHP-3.01", "none", "Permissive."),
        ToolLicense("perl", "Artistic-1.0-Perl OR GPL-1.0-or-later", "none", "Permissive."),
        ToolLicense(
            "openssl",
            "Apache-2.0",
            "review",
            "Apache-2.0 since 3.0; 1.x is under the older OpenSSL/SSLeay dual "
            "license, which is incompatible with GPL-2.0 without an exception. "
            "Which one applies depends on the version installed.",
        ),
    )
}


def license_for(tool: str) -> ToolLicense | None:
    """The license for a tool, or `None` when it is not in the table.

    Never guesses. A tool absent here is reported as unknown, and a reader can
    tell the difference between "permissive" and "nobody checked" -- which is
    the only property that makes an inventory worth having.
    """
    return TOOL_LICENSES.get(tool)


def toolchain_licenses(report: ScanReport) -> dict[str, Any]:
    """A license inventory of the tools that actually resolved on this machine.

    Active installations only. A license report listing every version of Python
    on the disk describes the disk; the question is what this project builds
    with.
    """
    known: list[dict[str, Any]] = []
    unknown: list[str] = []
    for tool in sorted(report.tools, key=lambda t: t.name):
        if not tool.is_active:
            continue
        entry = license_for(tool.name)
        if entry is None:
            unknown.append(tool.name)
            continue
        row = entry.as_dict()
        row["version"] = tool.version
        known.append(row)

    obligations = sorted({row["obligation"] for row in known if row["obligation"] != "none"})
    return {
        "schema_version": "1.0",
        "scope": (
            "Licenses of the build toolchain, not of this project's "
            "dependencies. Building with a tool does not place the output "
            "under that tool's license; the `obligation` field says where a "
            "real obligation exists."
        ),
        "tools": known,
        "unknown": unknown,
        "obligations_present": obligations,
    }
