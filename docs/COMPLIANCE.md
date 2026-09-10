# Compliance evidence

Three commands produce documents that leave the machine and get read by
somebody who did not run them: an auditor, a security reviewer, a customer's
procurement team. That reader is the design constraint for all three, and it
is why each one spends as much space on what it does **not** claim as on what
it found.

| Command | Produces | Signs / sends anything |
|---|---|---|
| `devrepro attest` | An in-toto statement about an environment | No |
| `devrepro evidence` | Named controls mapped to scan facts, or a toolchain license inventory | No |
| `devrepro advisories` | Toolchain versions checked against an offline advisory set | No |

Nothing here contacts a network. That is the same rule as the rest of the
tool, and here it also happens to be what makes the feature work in the place
that needs it most: an air-gapped build host is exactly where nobody has
looked at the toolchain in two years.

---

## `devrepro attest` — evidence somebody else can verify

`devrepro sign-snapshot` already exists and signs a snapshot with an HMAC.
That proves to *you* that *your own* file did not change. It is worth nothing
as evidence to anybody else, because HMAC is a shared secret: verifying the
signature requires holding the key that could have forged it. An auditor who
could have produced the evidence has not verified it.

The missing piece was a format, not a signature. `attest` emits an
[in-toto Statement v1](https://github.com/in-toto/attestation) — the shape
cosign, Sigstore, GitHub's attestation API and the SLSA verifiers already
read.

```bash
devrepro snapshot -o snap.json
devrepro attest snap.json -o statement.json
```

Three kinds:

- `--kind environment` (default) — what was installed, what the scan found,
  and what score the machine earned. The score and the finding counts are
  carried in the predicate deliberately: they cannot be recomputed from a list
  of versions afterwards.
- `--kind reproduction --environment-digest <sha256>` — binds an artefact to
  the environment attestation it came out of. Two digests, and the
  relationship between them is the entire claim.
- `--kind provenance` — SLSA Provenance v1 for a container this tool wrote the
  recipe for.

### Why it prints the cosign command instead of running it

Signing with Sigstore opens a browser for an OIDC flow and writes an entry to
a **public, permanent transparency log**. That is the most irreversible action
anywhere near this project, and there is no honest way to ask for "publish an
immutable record of this machine's identity" from inside a diagnostic command.
So `attest` does everything up to that step and hands you the command:

```bash
cosign attest-blob --predicate statement.json \
  --type https://devrepro.dev/attestation/environment/v1 \
  --output-attestation statement.json.att snap.json
```

### SLSA level, stated honestly

Provenance written by the same machine that ran the build is **level 1**: it
records what happened, not that nothing could have tampered with it. Level 2
requires a hosted build platform the developer does not control, and this
document says so rather than claiming it. Level 1 is still worth emitting — it
is the entry requirement for most consumers, and it is the document a hosted
builder later replaces rather than invents.

---

## `devrepro evidence` — controls, and the ones this cannot answer

A questionnaire asks about *Annex I Part II (1)*. This tool emits
`python/version-mismatch`. Both describe the same world; neither name appears
in the other's document. `evidence` is that translation table, for the CRA,
NIST SSDF (which EO 14028 points at) and SLSA.

```bash
devrepro evidence --framework cra
devrepro evidence -o evidence-pack.json
```

**Most controls are out of scope, and that is the feature.** A compliance
export that reports green across a whole framework hands somebody a document
that is wrong, which is worse than shipping nothing. Every control is either
evidenced by something in a scan report or marked `out-of-scope` **with a
reason** — and the reason travels in the exported file, not just in this page.

Four statuses:

| Status | Means |
|---|---|
| `evidenced` | This report contains the facts an assessor asked for |
| `not-evidenced` | The scan found nothing for this control — an empty answer, not a passing one |
| `out-of-scope` | A machine scan cannot speak to it; the reason is given |
| `partial` | Some of what the control asks for |

`evidenced` does **not** mean the control is satisfied. That judgement needs a
person who knows what the product is, and no scan can make it. The exported
file says this at the top, above the table, because that is the sentence the
reader has to see first.

### `--licenses`

```bash
devrepro evidence --licenses
```

An inventory of the *toolchain's* licenses — a question every SBOM tool skips,
because the compiler is in no lockfile. The short answer, which the report
leads with: **compiling a program with a tool does not put you under that
tool's license.** GCC ships a Runtime Library Exception for exactly this.

Each row carries an obligation alongside the SPDX identifier, because
`GPL-2.0-only` next to `git` with no further explanation tells a legal team
something false:

- `none` — permissive, or an exception covers the output.
- `redistribution-only` — building creates no obligation; shipping the tool
  itself (inside a container image, say) does.
- `review` — the answer depends on which distribution you have. An OpenJDK
  build and an Oracle JDK are not the same license question.

A tool absent from the table is reported as unknown rather than guessed at. An
inventory whose rows were inferred is not an inventory, and the reader has no
way to tell which rows were which.

---

## `devrepro advisories` — the toolchain nobody scans

Every scanner walks the dependency tree. Almost none check what *built* it. A
project can have a perfectly clean `npm audit` and be compiled by a `git` old
enough that cloning a repository executes code from it.

```bash
devrepro advisories
```

It is also part of every `doctor` scan, as the `advisories` rule pack.

### It is a seed, not a feed

The bundled set is small on purpose, and every entry carries a URL you can
open. A large bundled set would be a stale bundled set; the mechanism for
replacing it is the actual feature.

```bash
devrepro advisories --db /media/usb/advisories.json
```

An external bundle must be **signed**. This file decides which of your tools
get called dangerous, and the interesting attack on it is not adding a false
entry — it is quietly removing a true one, which no amount of reading the
output would reveal.

```bash
export DEVREPRO_ADVISORY_KEY="…"          # never commit it
devrepro advisories --db advisories.json   # advisories.json.sig must be beside it
```

`--trust-unsigned` accepts one without a signature, in as many words.

Bundle format:

```json
{
  "schema_version": "1.0",
  "published": "2026-08-08",
  "covers": ["git", "openssl"],
  "advisories": [
    {
      "id": "CVE-0000-00000",
      "tool": "git",
      "summary": "One sentence.",
      "fixed": ["2.45.1", "2.44.1", "2.43.4"],
      "introduced": "2.40.0",
      "reference": "https://example.org/advisory",
      "severity": "high"
    }
  ]
}
```

### `fixed` is a list because backports are how these ship

A fix released as 2.45.1, 2.44.1 and 2.43.4 means **2.44.0 is affected and
2.44.1 is not**. Comparing against the highest number gets that exactly
backwards, and the wrong answer looks entirely reasonable. So the installed
version's own `major.minor` branch is looked up first, and only if that branch
has no listed fix does it compare against the highest one.

**The failure mode, stated:** a version on a branch old enough that it never
received the fix compares against the highest fix and is reported affected.
That is usually right, and it is the safe direction for a warning. It is the
wrong direction for a gate — so nothing built on this blocks. `devrepro
advisories` exits `1` (READY_WITH_WARNINGS) on a match, never `2`.

The comparison is also offline, so it does not know whether your distribution
backported the fix into the version string you have. Many do. Check the
distribution changelog before treating a match as urgent.

### Silence is reported as silence

A tool the bundle has no data for produced **no answer**, which is not a clean
one. Both the command and the `advisories/coverage` finding name what the set
covers and when it was reviewed, whether or not anything matched, because the
whole failure mode of offline advisory data is being read as coverage.

---

## `devrepro history --verify` — tamper-evident history

The snapshot history directory is a pile of files. Edit one, delete another,
back-date a third, and afterwards it looks exactly like a directory where none
of that happened.

Each stored snapshot is recorded in an append-only chain (`chain.jsonl`) where
every entry commits to the digest of its snapshot *and* to the entry before
it. Editing any record changes every record after it; deleting one breaks the
link; reordering breaks it too.

```bash
devrepro history --verify
```

**What this does not do.** There is no secret involved, so anybody who can
write to the history directory can rebuild the whole chain from any point
forward as easily as it was built. A local hash chain is tamper-evident
against everyone who does not think to recompute it — which covers accidents,
sync conflicts and careless cleanup scripts, and does not cover a deliberate
adversary with write access.

What upgrades it is **anchoring**. The chain head is one short digest, and
`--verify` prints it. Record it anywhere the directory cannot reach — a commit
message, a ticket, a chat message — and everything up to that point is fixed
for good.
