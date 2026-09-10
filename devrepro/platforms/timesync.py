"""Where the clock gets its time from, which the skew check cannot tell you.

This project already detects clock skew, and skew is the symptom. The cause is
almost always that nothing is synchronising the clock at all -- a VM restored
from a snapshot, a container with no time source, a Windows machine whose
`w32time` service is stopped, or a domain-joined machine that fell back to
`Local CMOS Clock` and is now the authoritative source for its own drift.

Why it matters more than it sounds: a clock that is wrong by minutes breaks TLS
certificate validation, and the error it produces says the certificate is not
yet valid or has expired. Somebody then spends an afternoon on a certificate
that is fine. It also breaks Kerberos outright, silently invalidates cached
build artefacts whose timestamps now run backwards, and makes `make` rebuild --
or refuse to rebuild -- for reasons that never appear in any log.

A machine with no sync source is not skewed *yet*. That is the point of
checking the source rather than only the offset: the skew check finds the
problem after it has cost somebody a day.

All three platforms answer this differently and all three are parsed here
rather than shelling out to one and hoping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "UNSYNCHRONISED_SOURCES",
    "TimeSync",
    "parse_chronyc_tracking",
    "parse_timedatectl",
    "parse_w32tm_failure",
    "parse_w32tm_status",
]

#: Sources that mean "this machine is its own reference", i.e. nothing is
#: correcting it. Matched case-insensitively as substrings, because the exact
#: spelling differs between Windows versions and locales.
UNSYNCHRONISED_SOURCES: tuple[str, ...] = ("local cmos clock", "free-running", "unspecified")


@dataclass(frozen=True)
class TimeSync:
    """Whether the clock is being corrected, and by what."""

    #: `None` when the platform's query did not answer. Unknown is not "no".
    synchronised: bool | None = None
    source: str | None = None
    #: Present when the source is the machine itself.
    self_referential: bool = False
    detail: str | None = None

    @property
    def actionable(self) -> bool:
        """Whether there is something worth reporting.

        A synchronised clock with a real source produces no finding. Silence is
        the correct output for a machine that is fine.
        """
        return self.synchronised is False or self.self_referential


def _classify(source: str | None) -> bool:
    if not source:
        return False
    lowered = source.lower()
    return any(marker in lowered for marker in UNSYNCHRONISED_SOURCES)


_TIMEDATECTL_SYNC = re.compile(
    r"^\s*(?:System clock synchronized|NTP synchronized):\s*(\w+)", re.MULTILINE
)
_TIMEDATECTL_SERVICE = re.compile(
    r"^\s*(?:NTP service|systemd-timesyncd\.service active):\s*(\w+)", re.MULTILINE
)


def parse_timedatectl(text: str) -> TimeSync:
    """Read `timedatectl status` (systemd).

    Two fields, and they answer different questions: `NTP service` says whether
    a synchronising daemon is running, and `System clock synchronized` says
    whether it has actually converged. A machine that just booted has the first
    and not the second, which is normal and not a fault -- so the service being
    active is what saves it from a finding.
    """
    body = text or ""
    synced = _TIMEDATECTL_SYNC.search(body)
    service = _TIMEDATECTL_SERVICE.search(body)
    if not synced and not service:
        return TimeSync(detail="timedatectl did not report a synchronisation state.")

    is_synced = synced is not None and synced.group(1).lower() == "yes"
    service_active = service is not None and service.group(1).lower() in {"yes", "active"}

    return TimeSync(
        synchronised=is_synced or service_active,
        source="systemd-timesyncd or an NTP daemon" if service_active else None,
        detail=(
            "Clock is synchronised."
            if is_synced
            else (
                "An NTP service is running but the clock has not converged yet."
                if service_active
                else "No NTP service is running; nothing is correcting this clock."
            )
        ),
    )


_CHRONY_SOURCE = re.compile(r"^Reference ID\s*:\s*(.+)$", re.MULTILINE)
_CHRONY_STRATUM = re.compile(r"^Stratum\s*:\s*(\d+)", re.MULTILINE)


def parse_chronyc_tracking(text: str) -> TimeSync:
    """Read `chronyc tracking`.

    Stratum 0 means chrony is running and has no usable source -- the shape
    that looks healthiest from the outside and is doing the least.
    """
    source = _CHRONY_SOURCE.search(text or "")
    stratum = _CHRONY_STRATUM.search(text or "")
    if not source:
        return TimeSync(detail="chronyc did not report a reference.")

    reference = source.group(1).strip()
    unsynced = stratum is not None and stratum.group(1) == "0"
    return TimeSync(
        synchronised=not unsynced,
        source=reference,
        self_referential=_classify(reference),
        detail=(
            "chrony is running but has no usable time source (stratum 0)."
            if unsynced
            else f"chrony is tracking {reference}."
        ),
    )


_W32TM_SOURCE = re.compile(r"^Source:\s*(.+)$", re.MULTILINE)
_W32TM_STRATUM = re.compile(r"^Stratum:\s*(\d+)", re.MULTILINE)


def parse_w32tm_status(text: str) -> TimeSync:
    """Read `w32tm /query /status`.

    `Local CMOS Clock` as the source is the finding worth having: the machine is
    synchronising with itself, which is indistinguishable from not
    synchronising and looks like a configured service to anybody checking
    whether the service runs.
    """
    source = _W32TM_SOURCE.search(text or "")
    if not source:
        return TimeSync(detail="w32tm did not report a source; the service may be stopped.")

    reference = source.group(1).strip()
    self_ref = _classify(reference)
    return TimeSync(
        synchronised=not self_ref,
        source=reference,
        self_referential=self_ref,
        detail=(
            "The time source is the machine's own hardware clock, so nothing is "
            "correcting it. It will drift, and the first symptom is usually a TLS "
            "error that blames a certificate."
            if self_ref
            else f"Synchronising with {reference}."
        ),
    )


#: What `w32tm` says when the Windows Time service is not running. Matched on
#: the service message rather than the exit code: the code is a generic
#: 0x80070426 that also arrives for unrelated service problems, and the text is
#: the part that identifies the condition.
_SERVICE_STOPPED = re.compile(r"service has not been started", re.IGNORECASE)


def parse_w32tm_failure(text: str) -> TimeSync | None:
    """Read a *failed* `w32tm /query /status`, which is where the answer often is.

    This is the finding, not an absence of one. A stopped Windows Time service
    means nothing is correcting the clock, and the command reports that by
    exiting non-zero -- so a probe that only reads stdout on success discards
    exactly the machines it was written for. This one was found by running the
    probe on a real machine and getting silence.

    Returns `None` for any other failure, because "w32tm is not on PATH" and
    "the service is stopped" are different answers and only one of them is a
    problem with the clock.
    """
    if _SERVICE_STOPPED.search(text or ""):
        return TimeSync(
            synchronised=False,
            source=None,
            detail=(
                "The Windows Time service is not running, so nothing is correcting "
                "this clock. It has not drifted yet; it will."
            ),
        )
    return None
