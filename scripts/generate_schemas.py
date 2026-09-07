"""Generate the JSON Schemas in schemas/ from the Pydantic models.

ARCHITECTURE.md and schemas/README.md both describe `schemas/*.json` as
generated from `devrepro/core/models.py`. For a while no such files existed --
the directory held only a README, so `scripts/validate_schemas.py` globbed an
empty set and passed unconditionally, and SECURITY.md's "loaded snapshots are
validated against schemas" described a layer that was not there.

This script is the generator those documents assume. Run it after changing a
model; CI re-runs it and fails if the committed output has drifted.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from devrepro.core.models import EnvironmentDiff, ScanReport, Snapshot

SCHEMAS: dict[str, type] = {
    "snapshot.schema.json": Snapshot,
    "scan-report.schema.json": ScanReport,
    "environment-diff.schema.json": EnvironmentDiff,
}

_BASE_ID = "https://github.com/webdevsamran/devrepro-doctor/schemas"


def build(name: str, model: type) -> dict[str, object]:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"{_BASE_ID}/{name}"
    return schema


def main() -> int:
    out_dir = pathlib.Path(__file__).resolve().parents[1] / "schemas"
    out_dir.mkdir(exist_ok=True)
    changed = False
    for name, model in SCHEMAS.items():
        target = out_dir / name
        rendered = json.dumps(build(name, model), indent=2, sort_keys=True) + "\n"
        previous = target.read_text(encoding="utf-8") if target.is_file() else None
        if previous != rendered:
            target.write_text(rendered, encoding="utf-8")
            changed = True
            print(f"wrote  {target.name}")
        else:
            print(f"ok     {target.name}")
    if changed and "--check" in sys.argv:
        print(
            "error: committed schemas are stale; run scripts/generate_schemas.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
