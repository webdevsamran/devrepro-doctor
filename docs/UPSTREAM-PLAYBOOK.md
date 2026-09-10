# The upstream playbook

This project has one star. Nothing in it matters until somebody has a reason to
try it, and the honest list of ways to give them one is short.

Writing this down as a document rather than doing it quietly is deliberate. The
tactics below are the ones that work *because they are useful to the person
receiving them*, and the same actions done for reach instead of for the
recipient are spam. Keeping the distinction written down is what stops the
second version happening by drift.

---

## The one that works: answer the issue with the diagnosis

Every ecosystem has a permanent stream of issues that are environment problems
misfiled as bugs:

- "Works locally, fails in CI"
- "Fails on Windows only"
- "Cannot install on Apple Silicon"
- "Worked before I upgraded Node"

A maintainer triaging one of these is doing manual environment forensics. A
comment that does the forensics for them is welcome; a comment that advertises
a tool is not. The difference is entirely in what the comment *leads with*.

**Do:**

1. Reproduce or read the report properly first. If you cannot say what is
   different about the reporter's machine, you have nothing to contribute.
2. Lead with the finding. *"Your CI pins Node 22 and the reporter's `.nvmrc`
   says 20 — that is where the lockfile difference comes from."*
3. Mention the tool once, at the end, as how you got there. Once.
4. Attach the actual output if it is short, or a `devrepro reproduce` recipe if
   the failure is reproducible.

**Do not:**

- Post on issues you have not read.
- Post the same comment twice anywhere.
- Open a pull request adding this tool to somebody's CI unless they asked.
  Nobody wants an unsolicited dependency.
- Comment on an issue where the answer is not an environment problem. Being
  wrong in public about somebody else's bug is worse for the project than
  silence.

**The test:** if the tool did not exist, would the comment still be worth
posting? If no, do not post it.

---

## Second: fix the thing the diagnosis reveals

When the finding is a real bug in an upstream tool — a version detector that
misreads a shim, a setup action that pins a moving tag — the pull request that
fixes it is worth more than any number of comments. It also earns the right to
mention where the diagnosis came from, in a way a comment never quite does.

---

## Third: the corpus is the argument

`devrepro repro-rate` records how often reproductions actually work, and this
project intends to publish its own number. Nobody else in the category
publishes one, because it is going to be disappointing.

A tool that says *"reproduces 60% of reported environment failures, and here is
the breakdown of the other 40%"* is more credible than one implying 100%. The
40% is also the roadmap. That is a post worth writing once there is a corpus
behind it, and not before.

---

## What this deliberately does not do

**No aggregate telemetry, ever.** A "State of Dev Environments" report would be
the obvious content play and it needs a collection channel this project's
anti-goals forbid. Recorded in `PRODUCT_GAPS.md` as a decision, not a gap.

**No comparison posts.** The nearest analogue in this space reached 14,800
stars with a narrower scope and it does its job well. Its narrowness is the
opening — language-agnostic host diagnostics is unoccupied — and saying so is
different from arguing it is worse.

**No badge campaigns.** `agent-check --badge` exists because a maintainer might
want the number, not so that this project's name appears in READMEs.
