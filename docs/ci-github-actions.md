# Using DevRepro Doctor in GitHub Actions

Two integration levels are supported.

## 1. Job gate (preflight / guard)

Fail the job when the runner machine cannot build the project:

```yaml
- uses: webdevsamran/devrepro-doctor/action@main
  with:
    command: preflight
    # policy: .devrepro.toml
```

Exit-code contract: `0` READY · `1` READY_WITH_WARNINGS · `2` BLOCKED.
Set `fail-on-warnings: true` to fail on exit code 1 as well.

Use `command: guard` for a short-output variant suited to matrix jobs where
log noise matters. On a fresh runner, gating on the whole machine is the right
default -- everything the job will need has to be there.

## 1a. Commit hook (`guard --scope changed`)

The same default is wrong on a developer's machine. `guard` gates on every
finding anywhere, so a stopped Docker daemon would block a commit that touches
only Python source, and a hook that does that gets deleted.

`--scope changed` gates only when the commit alters the **environment
contract** -- a lockfile, manifest, toolchain pin, CI workflow, container
definition or `.devrepro.toml`. Scoping to changed files the way a linter does
would be meaningless here, because a machine has no per-file technical debt;
what changes is what the machine is being asked to provide. When nothing in the
contract moved, the gate exits `0` without scanning at all.

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: devrepro-contract-guard
      name: devrepro environment-contract guard
      entry: python -m devrepro guard --scope changed --quiet
      language: system
      always_run: true
      pass_filenames: false
```

`devrepro init --write` generates this hook for you. The kind of change also
decides which findings are relevant: a `pyproject.toml` change makes the Python
rules matter and leaves Docker alone, while a `.devrepro.toml` change re-opens
everything, because the policy is the declaration of what the machine must
provide.

Pass `--base origin/main` to gate a pull request on what the branch changed
rather than on the working tree.

## 2. Code scanning via SARIF

Write a SARIF report and upload it so environment blockers appear on the
Security tab and on pull requests:

```yaml
jobs:
  devrepro:
    runs-on: ubuntu-latest
    permissions:
      security-events: write   # required for SARIF upload
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: webdevsamran/devrepro-doctor/action@main
        with:
          command: doctor
          sarif-output: devrepro.sarif
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: devrepro.sarif
```

State mapping: BLOCKED/ERROR → SARIF `error`, WARN/UNKNOWN → `warning`,
INFO/PASS → `note`. Findings carry stable rule IDs (`node/version-mismatch`,
`path/duplicates`, …) plus detected/required versions and a remediation hint
when available. Run `devrepro rules` for the packs, and see
`scripts/capture_readme_example.py` for the id shapes the docs guard accepts.

## 2a. Annotations, for repositories SARIF cannot reach

SARIF is the better format, and uploading it from a **private** repository
requires GitHub Advanced Security. Most teams reading this do not have it, so
the SARIF section above works beautifully in a demo and does nothing where it
was needed.

Workflow commands cost nothing and work on every plan. `guard --format
annotations` writes them to stdout; GitHub reads them out of the log. No token,
no upload step, no permissions block:

```yaml
      - run: devrepro guard --format annotations --path .
```

Two things worth knowing before you turn this on:

**Most findings do not belong on a line of your diff.**
`containers/docker-daemon-unreachable` is a fact about the runner, not about a
file, so it is emitted without a `file=` property and GitHub renders it against
the workflow run instead. Only findings whose own evidence names a
repository-relative path get anchored to a line. Anchoring the rest to line 1 of
something would put "Docker is not running" on a line of your source, and that
is how a team learns to ignore every annotation in the run.

**GitHub renders at most ten annotations per level per step.** Past that, the
commands are accepted and silently not shown. `devrepro` emits a `::notice`
saying how many were dropped, so a truncated list does not read as a complete
one.

For a caller that holds a token, `--format check-run` builds a Check Run payload
to POST. It is built and never sent -- acquiring the permission to write checks
is a different product:

```yaml
      - run: devrepro guard --format check-run > check.json
      - run: gh api repos/${{ github.repository }}/check-runs --input check.json
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## 2b. Merge queues

A merge queue batches several pull requests and merges them together, so the
diff that matters is the whole batch against the base branch -- not any one
pull request. `guard --scope changed` already does the right thing; the only
subtlety is which ref to compare against.

`GITHUB_BASE_REF` is **empty for `merge_group` events**. The base is
`github.event.merge_group.base_ref`, and passing the wrong one makes the guard
compare against nothing and pass everything:

```yaml
on:
  merge_group:

jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # --base needs the history to diff against
      - run: |
          devrepro guard --scope changed             --base "${{ github.event.merge_group.base_ref }}"             --path .
```

`fetch-depth: 0` matters as much as the ref: a shallow checkout has no merge
base, `git diff` returns nothing, and the gate reports a clean contract for a
batch that changed every lockfile in the repository.

## Pull-request comment

`devrepro guard --format markdown` renders the verdict as a comment body and
prints it to stdout. It posts nothing itself: the workflow decides what happens
to the text, which is what keeps the no-telemetry guarantee something you can
check by reading the command rather than something you have to trust.

```yaml
name: Environment contract
on: pull_request

permissions:
  contents: read
  pull-requests: write

jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0        # `--base` needs the target branch present
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: pip install git+https://github.com/webdevsamran/devrepro-doctor@main

      - id: guard
        run: |
          devrepro guard --scope changed             --base "origin/${{ github.base_ref }}"             --format markdown > comment.md
          echo "code=$?" >> "$GITHUB_OUTPUT"
        continue-on-error: true

      - uses: peter-evans/create-or-update-comment@v4
        # ... or any equivalent. The body carries a stable marker,
        # `<!-- devrepro-doctor: environment-contract guard -->`, so a job can
        # find its own previous comment and edit it. A bot that appends on
        # every push turns a useful signal into fifteen near-identical comments
        # that people collapse and stop reading.
        with:
          issue-number: ${{ github.event.pull_request.number }}
          body-path: comment.md

      - name: Fail on blockers
        if: steps.guard.outputs.code == '2'
        run: exit 1
```

Pin third-party actions by SHA in a real workflow; the tags above are for
readability. This repository's own
[`scripts/check_action_pins.py`](https://github.com/webdevsamran/devrepro-doctor/blob/main/scripts/check_action_pins.py)
enforces that, and also checks that the `# vX.Y.Z` comment beside each SHA is
true — a comment that lies about the version is worse than no comment, because
it is what a reviewer actually reads.

## Other CI platforms

GitLab CI, Jenkins, Azure Pipelines and Bitbucket examples are on
[their own page](ci-other-platforms.md).

## Notes

- The composite action pins every third-party action by commit SHA.
- Until `devrepro-doctor` is published on PyPI, point the action at this
  repository: `package: git+https://github.com/webdevsamran/devrepro-doctor@main`.
- The scan is read-only; no machine data leaves the runner except what you
  explicitly upload.
