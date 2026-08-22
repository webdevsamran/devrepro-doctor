""".devrepro.toml policy loading and validation."""

from __future__ import annotations

import tomllib
from pathlib import Path

from devrepro.core.errors import PolicyError
from devrepro.core.models import (
    Policy,
    PolicyContainers,
    PolicyRequiredEnvNames,
    PolicySupportedOS,
)

__all__ = ["load_policy", "POLICY_FILENAME"]

POLICY_FILENAME = ".devrepro.toml"


def load_policy(path: Path | None = None) -> Policy:
    """Load a policy file. ``path=None`` searches CWD then parents."""
    target = path
    if target is None:
        cur = Path.cwd()
        for candidate in (cur, *cur.parents):
            p = candidate / POLICY_FILENAME
            if p.is_file():
                target = p
                break
    if target is None or not Path(target).is_file():
        raise PolicyError(
            f"No {POLICY_FILENAME} found.",
            hint="Create one in your project root; see README for the schema.",
        )
    try:
        data = tomllib.loads(Path(target).read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise PolicyError(f"Invalid policy file {target}: {exc}") from exc
    return _policy_from_toml(data)


def _policy_from_toml(data: dict[str, object]) -> Policy:
    supported_raw = data.get("supported_os") or {}
    if not isinstance(supported_raw, dict):
        raise PolicyError("[supported_os] must be a table")
    supported = PolicySupportedOS(
        windows=bool(supported_raw.get("windows", True)),
        linux=bool(supported_raw.get("linux", True)),
        macos=bool(supported_raw.get("macos", True)),
    )

    def _str_dict(key: str) -> dict[str, str]:
        raw = data.get(key) or {}
        if not isinstance(raw, dict):
            raise PolicyError(f"[{key}] must be a table of name = range strings")
        out: dict[str, str] = {}
        for k, v in raw.items():
            if not isinstance(v, str):
                raise PolicyError(f"[{key}].{k} must be a string range like '>=3.11'")
            out[str(k)] = v
        return out

    known_bad_raw = data.get("known_bad_versions") or {}
    if not isinstance(known_bad_raw, dict):
        raise PolicyError("[known_bad_versions] must be a table of lists")
    known_bad: dict[str, tuple[str, ...]] = {}
    for k, v in known_bad_raw.items():
        if isinstance(v, str):
            known_bad[str(k)] = (v,)
        elif isinstance(v, list):
            known_bad[str(k)] = tuple(str(x) for x in v)
        else:
            raise PolicyError(f"[known_bad_versions].{k} must be a string or list")

    containers_raw = data.get("containers") or {}
    if not isinstance(containers_raw, dict):
        raise PolicyError("[containers] must be a table")
    containers = PolicyContainers(
        require_devcontainer=bool(containers_raw.get("require_devcontainer", False)),
        require_compose=bool(containers_raw.get("require_compose", False)),
    )

    env_raw = data.get("required_env_names") or {}
    names: tuple[str, ...] = ()
    if isinstance(env_raw, dict):
        raw_names = env_raw.get("names", ())
        if isinstance(raw_names, list):
            names = tuple(str(n) for n in raw_names)
    elif isinstance(env_raw, list):
        names = tuple(str(n) for n in env_raw)

    return Policy(
        supported_os=supported,
        required_runtimes=_str_dict("required_runtimes"),
        required_tools=_str_dict("required_tools"),
        optional_tools=_str_dict("optional_tools"),
        known_bad_versions=known_bad,
        containers=containers,
        required_env_names=PolicyRequiredEnvNames(names=names),
    )