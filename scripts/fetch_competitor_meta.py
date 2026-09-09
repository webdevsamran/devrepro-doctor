"""Fetch live GitHub metadata for competitor repos via the authenticated gh CLI.

Writes data/competitor-meta.json and prints a compact TSV summary.
Access date is recorded for evidence purposes. Temp-free: writes only the
final artifact.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPOS = [
    "NixOS/nix",
    "cachix/devenv",
    "jetify-com/devbox",
    "jdx/mise",
    "asdf-vm/asdf",
    "direnv/direnv",
    "devcontainers/cli",
    "loft-sh/devpod",
    "coder/coder",
]


class FetchError(RuntimeError):
    """A competitor could not be fetched, and the run must not pretend it could."""


def gh_json(endpoint: str, *, allow_404: bool = False) -> dict[str, object] | None:
    """Fetch `endpoint`, raising rather than silently returning None.

    This used to swallow every failure into `None`, and the caller recorded
    that as `{"error": "repo-not-found-or-error"}` in the artifact. The
    competitive analysis then transcribed it as a fact about the world:
    "Optic -- repo gone (404)". Optic's repository is not gone. It is
    `opticdev/optic`, archived with 1,534 stars; this script was asking for
    `useoptic/optic`, which does not exist. A typo in a constant became a
    published claim that an archived competitor had disappeared, which is
    both wrong and the opposite of useful -- an archived incumbent in this
    exact domain is the most interesting fact in the file.

    `allow_404` is for endpoints where absence is a real answer (a repo with
    no releases). Everywhere else a 404 stops the run so a human decides
    whether the project moved or genuinely went away.
    """
    try:
        raw = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=True,
        ).stdout
        return json.loads(raw)  # type: ignore[no-any-return]
    except subprocess.CalledProcessError as exc:
        if allow_404 and "404" in (exc.stderr or ""):
            return None
        detail = (exc.stderr or "").strip()[:200]
        raise FetchError(
            f"{endpoint}: {detail}. "
            "If the project moved, update REPOS. If it really is gone, say so "
            "deliberately rather than letting a failed fetch write it."
        ) from exc
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise FetchError(f"{endpoint}: {type(exc).__name__}") from exc


def main() -> None:
    results: dict[str, dict[str, object]] = {}
    for repo in REPOS:
        meta = gh_json(f"repos/{repo}")
        rel = gh_json(f"repos/{repo}/releases/latest", allow_404=True)
        entry: dict[str, object] = {"repo": repo}
        if meta is None:  # pragma: no cover - gh_json raises instead now
            raise FetchError(f"{repo}: no metadata returned")
        else:
            lic = meta.get("license") or {}
            entry.update(
                {
                    "license_spdx": lic.get("spdx_id"),
                    "stars": meta.get("stargazers_count"),
                    "pushed_at": meta.get("pushed_at"),
                    "archived": meta.get("archived"),
                    "description": meta.get("description"),
                }
            )
        if rel is None:
            entry["latest_release"] = None
        else:
            entry["latest_release"] = {
                "tag": rel.get("tag_name"),
                "published_at": rel.get("published_at"),
            }
        results[repo] = entry

    payload = {
        "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": "gh api (authenticated)",
        "repos": results,
    }
    out = Path("data/competitor-meta.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for repo, entry in results.items():
        print(
            f"{repo} | {entry.get('license_spdx')} | {entry.get('stars')}"
            f" | {entry.get('pushed_at')} | {entry.get('latest_release')}"
        )


if __name__ == "__main__":
    main()
