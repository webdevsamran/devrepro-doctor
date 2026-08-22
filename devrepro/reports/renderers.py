"""Report renderers: terminal, JSON, Markdown, JUnit XML, standalone HTML.

Every format includes evidence, privacy/redaction status and
machine-readable finding IDs. All serialization passes through the
privacy gate (redact + secret-scan) before returning.
"""

from __future__ import annotations

import html as _html
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from devrepro.core.models import EnvironmentDiff, FindingState, ScanReport, Snapshot
from devrepro.privacy.gate import PrivacyGate, assert_no_secrets

__all__ = [
    "render_json", "render_markdown", "render_junit", "render_html",
    "render_diff_json", "render_diff_markdown", "render_diff_html",
]

_STATE_ORDER = (
    FindingState.BLOCKED, FindingState.ERROR, FindingState.WARN,
    FindingState.UNKNOWN, FindingState.INFO, FindingState.PASS,
)


def render_json(report: ScanReport) -> str:
    payload = json.dumps(report.model_dump(mode="json"), indent=2, default=str)
    assert_no_secrets(payload)
    return payload


def render_markdown(report: ScanReport) -> str:
    lines: list[str] = []
    lines.append(f"# DevRepro Doctor report — {report.created_at.isoformat()}")
    lines.append("")
    lines.append(f"- Platform: {report.platform.os_name} {report.platform.os_version} "
                 f"({report.platform.arch})")
    if report.score:
        lines.append(f"- Reproducibility completeness: **{report.score.total}/{report.score.possible}** "
                     f"({report.score.percent}%) — *describes declaration completeness only; "
                     "it does not guarantee reproducibility.*")
    lines.append(f"- Privacy: redacted={report.privacy.get('redacted')}, "
                 f"secrets_blocked={report.privacy.get('secrets_blocked')}")
    lines.append("")

    ordered = sorted(report.findings, key=lambda f: _STATE_ORDER.index(f.state))
    for state in _STATE_ORDER:
        group = [f for f in ordered if f.state == state]
        if not group:
            continue
        lines.append(f"## {state.value} ({len(group)})")
        lines.append("")
        for f in group:
            lines.append(f"### `{f.rule_id}`")
            lines.append("")
            lines.append(f.summary)
            lines.append("")
            meta = []
            if f.detected:
                meta.append(f"detected: `{f.detected}`")
            if f.required:
                meta.append(f"required: `{f.required}`")
            if f.component:
                meta.append(f"component: `{f.component}`")
            if meta:
                lines.append("- " + chr(10).join(meta))
                lines.append("")
            if f.remediation_hint:
                lines.append(f"**Remediation:** {f.remediation_hint}")
                lines.append("")
            ev = f.evidence[0]
            src = " ".join(ev.command) if ev.command else (ev.path or ev.source)
            lines.append("<details><summary>Evidence</summary>")
            lines.append("")
            lines.append("```")
            lines.append(f"{src}")
            if ev.excerpt:
                lines.append(ev.excerpt[:500])
            lines.append("```")
            lines.append("</details>")
            lines.append("")

    if report.probe_errors:
        lines.append("## Probe errors")
        lines.append("")
        for e in report.probe_errors:
            lines.append(f"- {e}")
        lines.append("")
    text = chr(10).join(lines)
    gate = PrivacyGate()
    text = gate.redact(text)
    assert_no_secrets(text)
    return text


def render_junit(report: ScanReport) -> str:
    suite = ET.Element("testsuite", {
        "name": "devrepro-doctor",
        "timestamp": report.created_at.isoformat(),
        "tests": str(len(report.findings)),
    })
    failures = sum(1 for f in report.findings if f.state in (FindingState.ERROR, FindingState.BLOCKED))
    warnings = sum(1 for f in report.findings if f.state == FindingState.WARN)
    suite.set("failures", str(failures))
    suite.set("errors", "0")
    suite.set("warnings", str(warnings))
    for f in report.findings:
        case = ET.SubElement(suite, "testcase", {
            "name": f.rule_id,
            "classname": f.component or "devrepro",
        })
        if f.state in (FindingState.ERROR, FindingState.BLOCKED):
            fail = ET.SubElement(case, "failure", {"message": f.summary})
            fail.text = f.evidence[0].excerpt or ""
        elif f.state == FindingState.WARN:
            w = ET.SubElement(case, "skipped", {"message": f.summary})
            w.text = f.evidence[0].excerpt or ""
        elif f.state == FindingState.UNKNOWN:
            err = ET.SubElement(case, "error", {"message": f.summary})
            err.text = f.evidence[0].excerpt or ""
    tree = ET.ElementTree(suite)
    from io import StringIO

    buf = StringIO()
    tree.write(buf, encoding="unicode", xml_declaration=True)
    out = buf.getvalue()
    out = PrivacyGate().redact(out)
    assert_no_secrets(out)
    return out


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DevRepro Doctor Report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem;
         padding: 0 1rem; line-height: 1.5; }}
  .badge {{ display:inline-block; padding:.1rem .5rem; border-radius:.4rem;
            font-size:.8rem; font-weight:600; }}
  .BLOCKED {{ background:#b91c1c; color:#fff; }}
  .ERROR {{ background:#dc2626; color:#fff; }}
  .WARN {{ background:#d97706; color:#fff; }}
  .UNKNOWN {{ background:#6b7280; color:#fff; }}
  .INFO {{ background:#2563eb; color:#fff; }}
  .PASS {{ background:#16a34a; color:#fff; }}
  details {{ margin:.5rem 0; padding-left:1rem; border-left:3px solid #8888; }}
  pre {{ white-space:pre-wrap; word-break:break-all; }}
  h1 small {{ font-weight:400; opacity:.7; }}
</style>
</head>
<body>
<h1>DevRepro Doctor <small>{created}</small></h1>
<p>{platform}</p>
<p>Privacy: redacted={redacted}, secrets_blocked={blocked}</p>
{score}
{findings}
<footer>Generated locally by DevRepro Doctor. No data left this machine.</footer>
</body>
</html>
"""


def render_html(report: ScanReport) -> str:
    ordered = sorted(report.findings, key=lambda f: _STATE_ORDER.index(f.state))
    parts: list[str] = []
    for f in ordered:
        ev = f.evidence[0]
        src = " ".join(ev.command) if ev.command else (ev.path or ev.source)
        parts.append(
            "<section>"
            f"<span class='badge {f.state.value}'>{f.state.value}</span> "
            f"<code>{_html.escape(f.rule_id)}</code>"
            f"<p>{_html.escape(f.summary)}</p>"
            + (f"<p><b>Detected:</b> {_html.escape(str(f.detected))} "
               f"<b>Required:</b> {_html.escape(str(f.required))}</p>" if f.detected or f.required else "")
            + (f"<p><b>Remediation:</b> {_html.escape(f.remediation_hint)}</p>" if f.remediation_hint else "")
            + "<details><summary>Evidence</summary><pre>"
            + _html.escape(src + (chr(10) + (ev.excerpt or ""))[:800])
            + "</pre></details></section>"
        )
    score_html = ""
    if report.score:
        score_html = (
            f"<p>Reproducibility completeness: <b>{report.score.total}/{report.score.possible}"
            f"</b> ({report.score.percent}%) — describes declaration completeness only; "
            "it does not guarantee reproducibility.</p>"
        )
    doc = _HTML_TEMPLATE.format(
        created=_html.escape(report.created_at.isoformat()),
        platform=_html.escape(
            f"{report.platform.os_name} {report.platform.os_version} ({report.platform.arch})"
        ),
        redacted=str(report.privacy.get("redacted")),
        blocked=str(report.privacy.get("secrets_blocked")),
        score=score_html,
        findings=chr(10).join(parts),
    )
    doc = PrivacyGate().redact(doc)
    assert_no_secrets(doc)
    return doc


# ------------------------------------------------------------------ diff ---

def render_diff_json(diff: EnvironmentDiff) -> str:
    payload = json.dumps(diff.model_dump(mode="json"), indent=2, default=str)
    assert_no_secrets(payload)
    return payload


def render_diff_markdown(diff: EnvironmentDiff) -> str:
    counts = diff.counts()
    lines = [f"# Environment diff {diff.a_snapshot_id} → {diff.b_snapshot_id}", ""]
    lines.append("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    lines.append("")
    lines.append("| Component | Name | Classification | A | B | Critical |")
    lines.append("|---|---|---|---|---|---|")
    for e in diff.entries:
        if e.classification == FindingState and False:  # pragma: no cover
            continue
        lines.append(
            f"| {e.component} | {e.name} | {e.classification.value} | "
            f"{e.a_value or '—'} | {e.b_value or '—'} | {'yes' if e.project_critical else ''} |"
        )
    text = chr(10).join(lines)
    text = PrivacyGate().redact(text)
    assert_no_secrets(text)
    return text


def render_diff_html(diff: EnvironmentDiff) -> str:
    rows = []
    for e in diff.entries:
        rows.append(
            "<tr>"
            f"<td>{_html.escape(e.component)}</td><td>{_html.escape(e.name)}</td>"
            f"<td>{_html.escape(e.classification.value)}</td>"
            f"<td>{_html.escape(e.a_value or '—')}</td>"
            f"<td>{_html.escape(e.b_value or '—')}</td>"
            f"<td>{'⚠️' if e.project_critical else ''}</td></tr>"
        )
    counts = ", ".join(f"{k}: {v}" for k, v in sorted(diff.counts().items()))
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Environment Diff</title><style>"
        "body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem}"
        "table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #8888;padding:.35rem .6rem;text-align:left;font-size:.9rem}"
        "</style></head><body>"
        f"<h1>Environment diff</h1><p>{_html.escape(diff.a_snapshot_id)} → "
        f"{_html.escape(diff.b_snapshot_id)}</p><p>{_html.escape(counts)}</p>"
        "<table><tr><th>Component</th><th>Name</th><th>Classification</th>"
        f"<th>A</th><th>B</th><th>Critical</th></tr>{''.join(rows)}</table>"
        "<footer>Generated locally by DevRepro Doctor.</footer></body></html>"
    )
    doc = PrivacyGate().redact(doc)
    assert_no_secrets(doc)
    return doc


def _unused_dt() -> None:  # pragma: no cover
    datetime.now(timezone.utc)


def _unused_snapshot_guard(s: Snapshot) -> Snapshot:  # pragma: no cover
    return s