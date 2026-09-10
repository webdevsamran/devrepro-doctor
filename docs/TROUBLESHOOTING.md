# Troubleshooting: symptom to cause

Every entry here is a **symptom somebody actually sees**, mapped to the check
that names the cause. The order is by how often the symptom sends people to the
wrong place, because that is what a troubleshooting index is for — a list
organised by subsystem is a list you can only use once you already know which
subsystem it is.

---

## "The build works in CI and fails here" (or the reverse)

```bash
devrepro ci-diff .
```

Compares what the CI workflow pins against what this machine resolves. The
answer is usually a runtime version, and the second most common answer is that
the machine has two of something and CI has one.

If the versions match, the difference is in what each *declares*:

```bash
devrepro agent-check .    # what the docs say, vs what CI enforces
devrepro project .        # what the manifests actually require
```

---

## "It worked yesterday"

```bash
devrepro history            # what changed since the previous snapshot
devrepro drift              # the timeline, with root-cause hints
```

If there is only one snapshot, there is nothing to diff against, and that is
the usual case — nobody takes a snapshot on a Tuesday. `devrepro monitor
--schedule cron` prints a scheduler entry that fixes it for next time.

Two snapshots and forty differences?

```bash
devrepro bisect working.json broken.json
```

---

## "The compiler crashed" (exit code 137)

`137` is `128 + 9`: **SIGKILL**, from the kernel's OOM killer, which writes
nothing to the build log. It is not a compiler crash.

```bash
devrepro doctor --json | grep sandbox/
```

`sandbox/memory-parity` reports it when the container engine's ceiling is far
below the host's — Docker Desktop's default is the usual culprit.

---

## "no kernel image is available for execution on the device"

A CUDA compute-capability mismatch, in a message that does not contain the
words "compute capability". It arrives at runtime, on whichever device the
scheduler picked, so it looks intermittent.

```bash
devrepro doctor --json | grep gpu/
```

`gpu/mixed-architectures` names the two cards. `gpu/cuda-driver-too-old`
handles the other CUDA failure, `CUDA driver version is insufficient for CUDA
runtime version`, which names neither version.

---

## "The certificate is expired" (and it is not)

Check the clock before the certificate. A machine whose clock has drifted
rejects perfectly valid certificates with an error that blames them.

```bash
devrepro doctor --json | grep host/clock
devrepro network --allow-network      # the TLS chain, opt-in
```

`host/clock-unsynchronised` catches the cause: nothing is correcting the clock,
so it has not drifted *yet*.

---

## "The build is slow on my machine only"

Three causes, in order of how much time they account for:

```bash
devrepro doctor --json | grep -E "host/slow-filesystem|host/antivirus|caches/"
```

1. **The tree is on the wrong filesystem.** A WSL shell under `/mnt/c`, or a
   project on an SMB share, pays a millisecond per file operation instead of a
   microsecond. A dependency install performs hundreds of thousands of them.
2. **Real-time scanning inspects the build directories.** On Windows, every
   file the build opens is scanned synchronously.
3. **The compiler cache is not helping.** A cache with a 15% hit rate is
   spending time, not saving it — usually because it is smaller than the
   working set.

And if the whole machine feels slow to *start*:

```bash
devrepro doctor --json | grep shell/slow-startup
```

---

## "Command not found" for something that is installed

```bash
devrepro which <tool>
devrepro path
```

Usually a version manager whose shims are on PATH after the real installation,
or a Windows App Execution Alias — a zero-byte stub that resolves and does
nothing.

---

## "npm install rewrote the whole lockfile"

```bash
devrepro doctor --json | grep lockfiles/
```

A package manager below the lockfile's format floor does not report an error;
it rewrites the tree, and the diff turns up in somebody else's pull request.

---

## "It fails in the container and works on the host"

```bash
devrepro reproduce . --failing-command "<the command>" --emit all
```

Then read the `PRECONDITION` lines in the generated Dockerfile before running
anything. They list what the recipe *cannot* carry — a database with data in
it, a GPU driver, a container engine — and a reproduction that fails for the
wrong reason costs more time than no reproduction.

---

## "An agent keeps flailing in this repository"

```bash
devrepro agent-check .
```

Reports which declared commands actually run, which CI gates the docs never
mention, and roughly what the gaps cost in wasted turns. `--gate` refuses to
start a session when the answer is bad enough.

---

## Nothing here matches

```bash
devrepro doctor
devrepro explain <rule-id>     # the long form of any finding
devrepro rules --catalogue     # every documented rule id
```

If a finding's explanation does not help, that is a bug worth reporting — the
rule id is the stable part, so quoting it is enough.
