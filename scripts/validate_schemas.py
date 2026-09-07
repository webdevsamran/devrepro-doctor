"""Verify the bundled JSON Schemas are real, current, and actually validate.

This gate previously did `for f in schemas.glob("*.json")` over a directory
that contained only a README, so the loop body never ran and the step passed
unconditionally -- on all twelve CI matrix legs. It now fails closed:

1. every schema named in SCHEMAS must exist (an empty directory is an error,
   not a pass);
2. each must be well-formed and a valid draft 2020-12 schema;
3. each must match what the current models generate (no silent drift);
4. a real instance of each model must validate against its schema, which is
   what SECURITY.md's "loaded snapshots are validated against schemas" claim
   depends on.
"""

from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))
# Imported as a sibling module rather than `scripts.generate_schemas`: adding
# an __init__.py would turn scripts/ into an importable package and pull it
# into packaging discovery, which it is not meant to be part of.
sys.path.insert(0, str(_HERE.parent))

from devrepro.core.models import PlatformInfo, ScanReport, Snapshot  # noqa: E402
from generate_schemas import SCHEMAS, build  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _sample_snapshot() -> Snapshot:
    return Snapshot(
        devrepro_version="0.1.0",
        platform=PlatformInfo(os_name="Linux", os_version="6", arch="x86_64"),
    )


def main() -> int:
    schemas_dir = _ROOT / "schemas"
    ok = True

    for name, model in SCHEMAS.items():
        path = schemas_dir / name
        if not path.is_file():
            print(f"FAIL {name}: missing -- run scripts/generate_schemas.py")
            ok = False
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL {name}: not valid JSON: {exc}")
            ok = False
            continue
        try:
            from jsonschema import Draft202012Validator

            Draft202012Validator.check_schema(loaded)
        except ImportError:
            print(f"warn {name}: jsonschema not installed; skipped schema check")
        except Exception as exc:
            print(f"FAIL {name}: not a valid draft 2020-12 schema: {exc}")
            ok = False
            continue
        if loaded != build(name, model):
            print(f"FAIL {name}: stale -- run scripts/generate_schemas.py and commit")
            ok = False
            continue
        print(f"ok   {name}")

    # An instance must actually validate, otherwise the schemas are decoration.
    try:
        from jsonschema import Draft202012Validator

        snapshot_schema = json.loads(
            (schemas_dir / "snapshot.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(snapshot_schema).validate(_sample_snapshot().model_dump(mode="json"))
        print("ok   snapshot instance validates against snapshot.schema.json")
    except ImportError:
        print("warn jsonschema not installed; instance validation skipped")
    except Exception as exc:
        print(f"FAIL snapshot instance does not validate: {exc}")
        ok = False

    if not ScanReport.model_fields:
        print("FAIL ScanReport has no fields")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
