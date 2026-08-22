# Contributing to DevRepro Doctor

Thank you for helping kill "works on my machine"! 🩺

## Ground rules

1. **Read-only default is sacred.** Any feature that mutates a system must be
   dry-run by default, risk-tiered, and gated behind explicit confirmation.
2. **Privacy is non-negotiable.** Never capture usernames, home directory
   absolute paths, tokens, keys, or credential material in findings/evidence.
   Add synthetic-secret tests for anything that reads env vars or config files.
3. **One failing probe must never crash a scan.** Wrap risky operations; the
   probe engine isolates failures by design.
4. **Never invent exact versions.** Requirements come only from what projects
   actually declare in manifests/lockfiles/policies.
5. **`main` is the only permanent branch.** Reconcile useful work into main,
   delete stale branches, never rewrite published history.

## Development setup

Requires Python 3.11+ and Node 18+ (for the frontend).

```bash
git clone https://github.com/webdevsamran/devrepro-doctor
cd devrepro-doctor
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[test,lint]"
pre-commit install

cd web && npm ci && cd ..          # frontend deps
```

## Running checks locally

```bash
ruff check devrepro tests && ruff format --check devrepro tests
mypy                                # strict mode
pytest                              # full suite, fixture-driven
pytest --cov=devrepro --cov-report=term-missing
cd web && npm run lint && npm run typecheck && npm test && npm run build
```

## Project layout

See ARCHITECTURE.md for the module map and data flow. Key contracts:

- **Probes**: subclass `devrepro.probes.base.Probe`, return `ProbeResult`
  with typed `Finding`s and `Evidence`. Register via entry point group
  `devrepro.probes`.
- **Rules**: subclass `devrepro.rules.base.Rule`; packs live under
  `devrepro/rules/packs/<name>.py`. Entry point group `devrepro.rules`.
- **Remediations**: subclass `devrepro.remediation.base.Remediation`;
  must declare `risk`, `preconditions`, `changes`, `rollback`.
  Entry point group `devrepro.remediations`.
- **Project detectors**: implement `ProjectDetector`; entry point group
  `devrepro.project_detectors`.
- **Exporters**: implement `Exporter`; entry point group `devrepro.exporters`.

Plugin APIs are versioned: see `docs/plugins.md`.

## Testing requirements

- Tests must **not depend on the real developer machine**. Use fixtures in
  `tests/fixtures/` and inject fake command runners.
- Use property-based tests (`hypothesis`) for version-range logic, PATH
  normalization, manifest parsers, and sanitization.
- Every new redaction surface needs a synthetic-secret regression test.

## Commit style

Conventional commits: `feat(probes): add rustup probe`, `fix(diff): ...`,
`docs: ...`, `ci: ...`. Logical commits pushed to `main` after validation.

## Release

Maintainers cut releases per docs/release.md (checksums + provenance).
Do not claim Homebrew/winget/Scoop availability until those packages exist.

## Questions

Open a discussion or issue. For security matters, see SECURITY.md.