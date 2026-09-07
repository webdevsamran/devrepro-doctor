# AGENTS.md

Working notes for AI coding agents in this repository. Everything here is
checked against CI — if a command below disagrees with
`.github/workflows/ci.yml`, the workflow wins and this file is the bug.

## What this project is

`devrepro` diagnoses developer machines, project toolchains and containers,
then produces a *safe repair plan*. It reports evidence rather than guessing,
and it never applies a fix the user did not ask for. Two properties follow
from that and are treated as correctness, not style: findings carry evidence,
and nothing sensitive leaves the machine.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

Python 3.11 is the floor. CI runs a full 3 OS × 4 Python matrix
(ubuntu/windows/macos × 3.11–3.14) — twelve legs, all required. Node 22 for
the frontend.

## Commands CI runs

```bash
ruff check devrepro tests
ruff format --check devrepro tests
mypy devrepro
pytest -q --cov=devrepro --cov-fail-under=70
python scripts/validate_schemas.py
pip-audit --skip-editable
mkdocs build --strict
cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

`fail_under = 70` is in `pyproject.toml` as well as on the CI command line, so
a local `pytest --cov` enforces the same floor CI does.

## Rules that are not style preferences

**Privacy is structural, not advisory.** `devrepro/privacy/` sanitizes before
anything is serialized. Do not add a field to a snapshot or report without
checking it passes through that path — `tests/test_privacy.py` covers this and
`SECURITY.md` makes promises about it.

**Findings carry evidence.** A `Finding` without an `Evidence` is not a
finding. If a probe cannot substantiate a claim, it reports `state=unknown`
rather than guessing.

**Exit codes are a public contract.** `devrepro/core/exit_codes.py` says so
explicitly: never change the meaning of an existing code, only append. CI
gates and onboarding scripts depend on them.

**Documented output is captured, never written.** The README's scan example
comes from `scripts/capture_readme_example.py`, which renders a fixture
through `render_terminal_table` -- the same function `devrepro doctor` calls
-- and `--check` fails CI on drift. It previously showed a rule id
(`python/multiple-installations`) that no code emits, in an `Evidence:` /
`Safe remediation:` layout the renderer cannot produce, under the caption
"examples from actual scans". The capture refuses to run if the example names
a rule id nothing emits.

**Schemas are generated, not hand-written.** `schemas/*.json` come from the
Pydantic models via `python scripts/generate_schemas.py`. Run it after
changing a model and commit the result; `scripts/validate_schemas.py` fails
if the committed files are stale, missing, or fail to validate an instance.

**Probes are tested against recorded output.** `tests/fixtures/recordings/`
holds real command output for ubuntu/fedora/macos/windows/wsl/docker. That is
what makes probe tests deterministic on a runner that has none of those
tools — add a recording rather than mocking ad hoc.

## Do not touch without being asked

- `devrepro/core/exit_codes.py` — see above.
- `action/action.yml` — it is a published GitHub Action; its inputs are a
  public interface. Note it passes inputs via `env:` deliberately, so that
  `${{ }}` expansion cannot inject shell, and reads `${PIPESTATUS[0]}` rather
  than `$?` because the command is piped through `tee`.
- `scripts/branch-protection.json` — contexts must match CI job names
  byte-for-byte, including the `(os, python-version)` matrix suffix. A
  mismatch leaves pull requests waiting on a check that never arrives.

## Conventions

Conventional commits with scopes (`feat(probes): add rustup probe`). Typed
Python; `mypy` must pass clean. `main` is the only permanent branch.
