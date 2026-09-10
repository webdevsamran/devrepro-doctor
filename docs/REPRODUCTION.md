# Reproduction

The README opens by promising to answer *"Docker works there but not here"*.
A diff tells a maintainer what is different. A **reproduction** tells them they
are looking at the right thing.

| Command | Answers |
|---|---|
| `devrepro reproduce` | Give me a container somebody else can run that fails the same way |
| `devrepro bisect` | Forty differences; which one matters? |
| `devrepro repro-rate` | How often does any of this actually work? |

Nothing here builds an image or runs a command. Building downloads gigabytes
and running the failing command executes what the project told us to execute;
both are your decision, and the recipe is the artefact — reviewable, diffable,
attachable to an issue.

---

## `devrepro reproduce`

```bash
devrepro reproduce . \
  --failing-command "pytest -q tests/test_import.py" \
  --symptom "ImportError: libssl.so.1.1" \
  --emit all -o ./repro
```

The verb is `reproduce`, not `generate`. `generate` already means "draft a
config from what I detected", which is a different job with a different failure
mode, and one verb doing both would leave them sharing a set of flags that half
apply.

### What makes it a reproduction rather than a Dockerfile

**The assertion.** A recipe that sets up an environment and stops is a
Dockerfile. A reproduction ends by running the thing that failed — so when
somebody fixes the cause, **the recipe stops working**, which is the signal
anybody actually wants from it. Without `--failing-command` you get an
environment draft, and the file says so in its own header.

The failing command goes in `CMD`, not `RUN`. A `RUN` that fails aborts the
build, and an aborted build is indistinguishable from a broken recipe.

**The pin.** `FROM python:3.12` reproduces a different thing next month.
`--pin` resolves the base to an immutable digest; it is opt-in because
resolving a digest contacts a registry. Where it cannot resolve one, the file
says `NOT PINNED` rather than pretending.

**The preconditions.** Local state that cannot cross a machine boundary is
listed rather than silently omitted:

| Precondition | Why it cannot travel |
|---|---|
| `no-install-step` | No lockfile this understands, so nothing installs dependencies — the command will die with "not found" |
| `container-in-container` | Reproducing needs a mounted socket, which is a privilege escalation, not a build step |
| `gpu` | Needs the host driver passed through, at a matching version |
| `platform` | The failure was seen on Windows or macOS; path separators, case sensitivity and line endings will not reproduce on Linux |

A recipe that fails for the *wrong reason* wastes more of a maintainer's time
than no recipe, because they debug the failure they were handed.

### Formats

`--emit dockerfile | script | compose | devcontainer | nix | all`

One recipe, five views of it, so a Dockerfile and a flake describing the same
failure cannot drift apart.

`repro.sh` prints the interpretation rather than leaving it to an exit code,
because the counter-intuitive part of a reproduction is that **success is
failure**: a recipe that exits zero has not reproduced the bug, and somebody
reading a green tick will draw the opposite conclusion from the right one.

The Nix output is a `devShell`, not a build. A flake claiming to build the
project would claim to have understood the build, which nothing here has done.
It is interop rather than competition: this project diagnoses environments, Nix
manages them.

### Sandboxes

```bash
devrepro reproduce . --sandbox e2b        # e2b.Dockerfile
devrepro reproduce . --sandbox daytona    # .devcontainer/devcontainer.json
devrepro reproduce . --sandbox container-use
```

Configuration files, not API clients. Integrating with three sandboxes would
mean three credential stores and three release cadences inside a tool whose
value proposition is that it contacts nothing — and a tool that speaks their
file formats survives the consolidation that is coming for that market, while
one with three vendor SDKs pinned in its dependency tree does not.

The filename matters: each of these tools discovers its configuration by path,
so a correctly-shaped file under the wrong name is invisible.

### Keeping a committed recipe honest

```bash
devrepro reproduce . --emit all -o ./repro --check
```

Regenerates and compares, the same shape as `generate_schemas.py --check`, so a
committed recipe that has quietly stopped describing the project fails a CI job
instead of failing a maintainer six months from now. Writes nothing either way.

The comparison **ignores the timestamp lines**. A recipe is stale when what it
*describes* has changed, not when it was regenerated — and the first version of
this check reported every file stale the instant after writing it, because the
header carries a scan time.

```yaml
      - run: devrepro reproduce . --emit all -o ./repro --check
```

---

## `devrepro bisect`

```bash
devrepro bisect working.json broken.json
devrepro bisect working.json broken.json --minimise
```

Two snapshots and forty differences. Everybody's instinct is to read the diff
and pick the suspicious-looking line, which works when the cause is a runtime
version and fails completely when it is a locale, a PATH order or a variable
nobody thinks about. Bisection does not care what looks suspicious.

**It applies nothing.** Applying an environment dimension means editing a PATH,
installing a version or setting a variable on your machine — the whole class of
action this project does not take unasked. It proposes a candidate set, you
apply it and answer, it halves the space. The `git bisect` interface, because
that is the one everybody already knows.

Two sanity checks run first, and skipping them is how a bisect returns a
confident wrong answer:

- If applying **nothing** already fails, the "working" environment does not
  work either and every later verdict is noise.
- If applying **everything** does not fail, the cause is not in this diff, and
  the search would otherwise converge on whichever dimension came last.

Both are reported as inconclusive rather than as a culprit.

### `--minimise`

Delta debugging (Zeller's ddmin) instead of bisection, and it answers the
question bisection structurally cannot: when two changes are each harmless and
break things only *together*, a bisect names one of them and is wrong in a way
that reads as right.

It costs more verdicts, and every verdict is a person applying a change and
running a build — so the search is bounded (`--max-verdicts`), and when the
bound bites it says the result may not be minimal rather than presenting it as
though it were.

---

## `devrepro repro-rate`

```bash
devrepro reproduce . --failing-command "…" -o ./repro
# …you run it, and then:
devrepro repro-rate --record different-failure --note "libssl, but a different version"
devrepro repro-rate
```

Every tool in this space claims to reproduce environments and none of them
publishes a rate. That is not an accident — the number is going to be
disappointing, because a machine's state includes things no container carries.
Publishing it anyway is more useful than implying 100% and letting every user
discover otherwise separately. The gap is also the roadmap.

| Outcome | Means |
|---|---|
| `reproduced` | The reported failure happened, with the reported symptom |
| `not-reproduced` | The command succeeded in the container |
| `different-failure` | Something failed, but not the reported thing |
| `could-not-build` | The recipe did not produce a runnable container |
| `precondition-unmet` | It needed something no container carries |

**`different-failure` counts as not reproduced.** That is the choice that
decides whether the number is honest: a recipe that built, ran and produced
some other error has reproduced nothing, and counting it as a success is how
every vendor benchmark reaches 95%.

Recording is explicit. Nothing infers success from an exit code, because "the
container ran" and "the failure reproduced" are different questions and only a
person can answer the second.

No rate is reported below ten attempts. A percentage from a handful is a number
somebody will quote and nobody can defend.

**It stays local.** The corpus is a file in your own history directory. Nothing
is uploaded and there is no aggregate anywhere — that is the shape this
project's anti-goals forbid, and the same reasoning that made a "State of Dev
Environments" report a documented non-goal.
