# Getting help with DevRepro Doctor

Start with the symptom, not the tool:
**[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** is indexed by what you
are seeing — *"the build works in CI and fails here"*, *"it worked yesterday"*,
*"command not found for something that is installed"*, *"an agent keeps flailing
in this repository"*.

If a finding is the confusing part, ask the tool:

```bash
devrepro explain <rule-id>      # what it means, why it matters, how to fix it
devrepro rules --catalog        # every rule id it can produce
```

---

## Reporting a bad diagnosis

**This is the most valuable thing you can send.** A scan that gets something
wrong on your machine is worth more than a feature request, because the whole
product is the claim that its findings are true.

Open an issue with:

1. **What you expected and what it said.** The rule id is enough to locate it.
2. **`devrepro doctor --json`** — the report, already redacted. Usernames, home
   directories, tokens, API keys and private hosts are removed before anything
   is serialized, and probable secrets block the export outright. Every report
   states what it collected.
3. **`devrepro snapshot -o snapshot.json`** if the problem is about versions,
   PATH or toolchains. A snapshot is the sanitized machine manifest, and it is
   what lets somebody reproduce your case without your laptop.

If you would rather check what is in those files first, that is the right
instinct and the answer is in [docs/PRIVACY.md](docs/PRIVACY.md).

## Reporting a crash

Include the exit code. It is part of a published contract and it narrows the
problem immediately: `3` is an internal error and always a bug here, `4` is a
usage error and may be a documentation bug, `2` means the machine is genuinely
blocked. See [docs/EXIT-CODES.md](docs/EXIT-CODES.md).

## Security

Do **not** open a public issue for a vulnerability.
[SECURITY.md](SECURITY.md) has the private channel and what to expect.

## Asking a question

[GitHub Discussions](https://github.com/webdevsamran/devrepro-doctor/discussions)
if they are enabled, otherwise an issue is fine. Questions about whether a
behaviour is intended are useful: several entries in
[PRODUCT_GAPS.md](PRODUCT_GAPS.md) exist because somebody asked why a thing was
missing and the honest answer turned out to be a decision worth writing down.

## What this project will not do

Before filing, it may save you time to know what is deliberately absent and
why — remote scanning over SSH, a hosted rule-pack registry, a TUI, telemetry of
any kind. Each is recorded with its reasoning in
[PRODUCT_GAPS.md](PRODUCT_GAPS.md). Absence here is usually a decision rather
than an oversight, and the file says which.

## Response times

This is maintained by one person alongside other work, under Apache-2.0, with
no company behind it. Expect days rather than hours. A bad diagnosis with a
report attached gets looked at first, because it is the kind of bug that makes
the tool untrustworthy rather than merely incomplete.

If the project is useful to you or your team,
[sponsorship](https://github.com/sponsors/webdevsamran) is what buys more of
that time — and the README explains exactly what it would go toward.
