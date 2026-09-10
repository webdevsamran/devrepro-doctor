# Environment bill of materials

```bash
devrepro scan --format cyclonedx -o environment.cdx.json
devrepro report scan.json --format cyclonedx      # re-render a saved report
```

## Why a second BOM

Every SBOM tool in circulation answers one question: what did this application
vendor in. None of them answers the other one -- what *built* it. The compiler,
the interpreter, the package manager, the container engine, the operating
system.

That second list is the one that turns a reproducible build into an
unreproducible one. Two machines with byte-identical lockfiles produce different
artefacts when one has glibc 2.17 and the other 2.39, or when one's container
engine emulates a different architecture. A dependency SBOM records neither.

It is also where regulation is heading. The Cyber Resilience Act's SBOM
obligations arrive in **December 2027**, and "the software this shipped with"
and "the machine it was built on" are separate questions that separate auditors
ask.

## What is in it

| CycloneDX field | What it carries |
|---|---|
| `metadata.component` | The host: OS name, version, architecture |
| `components[]` (`platform`) | The container engine, when one answered |
| `components[]` (`application`) | One entry per toolchain component, with its version |
| `purl` | `pkg:generic/<name>@<version>` for tools whose identity is well known |
| `properties[]` | Provenance, and how many installations were found |

CycloneDX rather than a bespoke format because an evidence file nobody's tooling
can read is not evidence.

## What is deliberately not in it

**Executable paths.** A path names a user's home directory on every platform,
and a BOM is an artefact people attach to compliance tickets and hand to
auditors outside their own company. What matters for reproducibility is the
*provenance* -- installed by the OS package manager, by rustup, by a version
manager, by a vendor installer -- and that is recorded instead. The document
says so in its own metadata, so someone looking for a path finds the reason
rather than a gap.

**The hostname.** Frequently a person's name or an unreleased project codename.
The host component is called `host`.

**One entry per resolved path.** A machine with three Pythons on PATH runs one
of them, and a BOM claiming three Python installations describes a fact about
PATH rather than about the build. The count is kept as a property, because
"there were three and this is the one that won" is exactly what a
reproducibility argument turns on.

**A PURL for tools that have no upstream identity.** A `purl` that resolves to
nothing is worse than none: it invites a scanner to look the component up and
report its absence as a finding.

## Determinism

The same report renders byte-identically, serial number included. A random UUID
would be more conventional and would make every regeneration a diff, which
defeats an artefact whose entire purpose is being compared -- between two
machines, or between the same machine last month and today.

Component identifiers are derived from the component's own identity rather than
from a counter, so a diff of two BOMs shows what changed instead of everything
having shifted by one line.

## Relationship to the release SBOM

This project also publishes an SPDX SBOM of its own dependencies at release
time, via `anchore/sbom-action`. The two do not overlap: that one describes
what `devrepro-doctor` is made of, this one describes the machine a build ran
on.
