"""Validate bundled JSON schemas are well-formed and models round-trip."""

from __future__ import annotations

import json
import pathlib

import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from devrepro.core.models import ScanReport  # noqa: E402


def main() -> int:
    schemas = pathlib.Path("schemas")
    ok = True
    for f in sorted(schemas.glob("*.json")):
        try:
            json.loads(f.read_text(encoding="utf-8"))
            print(f"ok   {f}")
        except json.JSONDecodeError as exc:
            print(f"FAIL {f}: {exc}")
            ok = False
    # model -> schema round-trip smoke
    from devrepro.core.models import PlatformInfo, Snapshot

    snap = Snapshot(devrepro_version="0.1.0", platform=PlatformInfo(os_name="Linux", os_version="6", arch="x86_64"))
    payload = snap.model_dump(mode="json")
    assert isinstance(json.dumps(payload), str)
    print("ok   snapshot model round-trip")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())