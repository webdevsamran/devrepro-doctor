"""Noticing that the machine changed, without becoming a thing that runs forever.

Drift is already detectable between two snapshots. What is missing is the
*habit*: nobody takes a snapshot on a Tuesday because nothing is wrong on a
Tuesday, so the first snapshot anybody has is taken after the build broke --
which is exactly one snapshot, and one snapshot diffs against nothing.

A monitor fixes that by taking one when nothing is wrong. Three constraints
shaped what it is allowed to be:

**No daemon.** A background process that survives reboots is something a person
has to notice, trust, update and eventually kill, and every developer machine
already has three of those. This runs when it is invoked -- from the user's own
scheduler, a shell profile, or by hand -- and exits.

**No network, ever.** The snapshots stay in the local history directory, the
same one `devrepro history` reads. There is nothing to send and nowhere to send
it, which is the whole difference between this and the class of tool that calls
itself a monitor.

**A budget, not a schedule.** The check is "has it been long enough since the
last snapshot" rather than "is it 09:00", because a machine that was asleep at
09:00 would otherwise never record anything, and the whole point is coverage
over time rather than a tidy series.

The cheap check comes first. Deciding whether to scan reads one directory
listing; the scan itself takes seconds. A monitor that scans in order to find
out whether it needed to scan is a monitor people uninstall.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DEFAULT_INTERVAL_HOURS",
    "MonitorDecision",
    "should_snapshot",
]

#: How stale the newest snapshot must be before another is taken. A day: drift
#: that matters -- a version manager update, an OS patch, a new install -- happens
#: at human intervals, and hourly snapshots would fill a history directory with
#: rows that all say the same thing.
DEFAULT_INTERVAL_HOURS = 24.0


@dataclass(frozen=True)
class MonitorDecision:
    """Whether to take a snapshot now, and the reason either way.

    The reason is not decoration: this runs unattended, and "it did nothing" is
    indistinguishable from "it is broken" unless it can say which.
    """

    snapshot: bool
    reason: str
    hours_since_last: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "reason": self.reason,
            "hours_since_last": self.hours_since_last,
        }


def should_snapshot(
    history_dir: Path,
    *,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
    now: float,
    suffix: str = ".json",
) -> MonitorDecision:
    """Whether enough time has passed since the newest stored snapshot.

    `now` is passed in as a monotonic-independent wall-clock float so a test
    drives this without waiting or patching the clock.

    Modification time rather than the name's timestamp. A snapshot copied in
    from another machine carries that machine's stamp in its filename, and
    trusting it would make a monitor decide it had already run today when it
    had not.
    """
    try:
        stamps = [
            path.stat().st_mtime
            for path in history_dir.glob("*" + suffix)
            if path.is_file() and path.name != "chain.jsonl"
        ]
    except OSError as exc:  # pragma: no cover - unreadable history directory
        return MonitorDecision(
            snapshot=False,
            reason=f"The history directory could not be read: {exc}",
        )

    if not stamps:
        return MonitorDecision(
            snapshot=True,
            reason=(
                "No snapshot has ever been stored. The first one is the one that "
                "makes every later diff possible, and nobody takes it on a Tuesday."
            ),
        )

    hours = (now - max(stamps)) / 3600
    if hours < 0:
        # A clock that moved backwards -- a VM restored from a snapshot, a
        # correction after NTP finally started. Treating a negative age as
        # "recent" would silently stop the monitor until the clock caught up.
        return MonitorDecision(
            snapshot=True,
            reason=(
                "The newest snapshot is dated in the future, so this machine's clock "
                "has moved backwards. Taking one now rather than waiting for the "
                "clock to catch up."
            ),
            hours_since_last=round(hours, 2),
        )

    if hours >= interval_hours:
        return MonitorDecision(
            snapshot=True,
            reason=f"{hours:.1f} hours since the last snapshot (interval {interval_hours:g}h).",
            hours_since_last=round(hours, 2),
        )

    return MonitorDecision(
        snapshot=False,
        reason=(
            f"Last snapshot was {hours:.1f} hours ago, inside the {interval_hours:g}h "
            "interval. Nothing to do."
        ),
        hours_since_last=round(hours, 2),
    )


def render_schedule(*, platform: str, interval_hours: float = DEFAULT_INTERVAL_HOURS) -> str:
    """The scheduler entry to install, printed rather than installed.

    Installing a scheduled task is a persistent change to somebody's machine
    made by a diagnostic tool, which is the class of action this project asks
    for by name. Printing it keeps the decision -- and the removal -- with the
    person who has to live with it.
    """
    if platform == "windows":
        return """# Windows Task Scheduler. Review, then run from an elevated PowerShell.
# Remove with: Unregister-ScheduledTask -TaskName devrepro-monitor

$action  = New-ScheduledTaskAction -Execute "devrepro" -Argument "monitor --snapshot"
$trigger = New-ScheduledTaskTrigger -Daily -At 12pm
Register-ScheduledTask -TaskName "devrepro-monitor" -Action $action -Trigger $trigger `
  -Description "Take a devrepro snapshot so later drift has something to diff against."
"""
    if platform == "macos":
        return f"""<!-- ~/Library/LaunchAgents/dev.devrepro.monitor.plist -->
<!-- Review, then: launchctl load ~/Library/LaunchAgents/dev.devrepro.monitor.plist -->
<!-- Remove with: launchctl unload <same path> -->
<plist version="1.0"><dict>
  <key>Label</key><string>dev.devrepro.monitor</string>
  <key>ProgramArguments</key>
  <array><string>devrepro</string><string>monitor</string><string>--snapshot</string></array>
  <key>StartInterval</key><integer>{int(interval_hours * 3600)}</integer>
  <key>RunAtLoad</key><false/>
</dict></plist>
"""
    return f"""# crontab entry. Review, then add with `crontab -e`.
# Remove by deleting the line.
#
# Noon rather than midnight: a laptop is more likely to be awake, and a
# schedule that only fires when the machine is asleep records nothing at all.
0 12 * * * devrepro monitor --snapshot >/dev/null 2>&1
# interval enforced by devrepro itself: {interval_hours:g}h
"""
