"""Command execution abstraction.

All probes shell out through :class:`CommandRunner` so tests can inject
recorded fixture output instead of touching the real machine. The
production runner never uses a shell (no ``shell=True``), applies a
timeout, and captures stdout/stderr without echoing secrets.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

__all__ = ["CommandResult", "CommandRunner", "SubprocessRunner", "RecordingRunner"]


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a single command execution."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    not_found: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.not_found and self.returncode == 0


class CommandRunner(Protocol):
    """Anything that can execute a command for a probe."""

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Production runner backed by :mod:`subprocess` (no shell)."""

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=dict(env) if env is not None else None,
                cwd=cwd,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, "", "", not_found=True)
        except subprocess.TimeoutExpired:
            return CommandResult(argv, 124, "", "", timed_out=True)
        except OSError as exc:
            return CommandResult(argv, 126, "", str(exc))
        return CommandResult(argv, proc.returncode, proc.stdout or "", proc.stderr or "")


class RecordingRunner:
    """Test double: replays canned results keyed by the first argv token.

    ``responses`` maps a command name (e.g. ``"git"``) to either a single
    :class:`CommandResult` or a list consumed in order (for repeated
    invocations). Unmapped commands return ``not_found``.
    """

    def __init__(
        self,
        responses: Mapping[str, CommandResult | Sequence[CommandResult]] | None = None,
        *,
        default: CommandResult | None = None,
    ) -> None:
        self._responses: dict[str, list[CommandResult]] = {}
        for key, value in (responses or {}).items():
            if isinstance(value, CommandResult):
                self._responses[key] = [value]
            else:
                self._responses[key] = list(value)
        self._default = default
        self.calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        queue = self._responses.get(argv[0])
        if queue:
            return queue.pop(0)
        if self._default is not None:
            return self._default
        return CommandResult(argv, 127, "", "", not_found=True)