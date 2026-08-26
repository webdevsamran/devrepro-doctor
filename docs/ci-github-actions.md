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

Use `command: guard` for a short-output variant suited to pre-commit hooks
and matrix jobs where log noise matters.

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
`python/multiple-installations`, …) plus detected/required versions and a
remediation hint when available.

## Notes

- The composite action pins every third-party action by commit SHA.
- Until `devrepro-doctor` is published on PyPI, point the action at this
  repository: `package: git+https://github.com/webdevsamran/devrepro-doctor@main`.
- The scan is read-only; no machine data leaves the runner except what you
  explicitly upload.
