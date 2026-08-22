# Synthetic Machine Fixtures

Recorded, privacy-safe command outputs and environment shapes used by the
test suite (`tests/`) to simulate machines we do not own. **Nothing here is
read from a real developer machine at test time** — probes are driven through
`RecordingRunner` with these canned results.

## Layout

| Path | Simulates |
| --- | --- |
| `windows/path.txt` | Windows PATH with duplicates, dead entries, Store alias |
| `ubuntu/path.txt` | Debian/Ubuntu PATH via apt + snap + pyenv |
| `fedora/path.txt` | Fedora PATH via dnf + rustup |
| `macos/path.txt` | macOS PATH via Homebrew + nvm |
| `wsl/status.txt` | `wsl --status` UTF-16 output shape |
| `docker/failures.json` | Docker daemon failure modes (pipe/socket/auth) |

## Rules for contributors

- Fixtures must contain **no real usernames, home paths, tokens or hosts**;
  use `<user>`, `/home/<user>` placeholders.
- When you add a probe code path, add the fixture that exercises it here and
  wire it in `tests/conftest.py`.