import { useMemo, useState } from 'react'
import type { EnvironmentDiff, ScanReport } from '../types'
import { Badge, Card, CopyButton, EmptyState, EvidenceDrawer, SeverityFilter } from '../components/ui'

type PageProps = { report: ScanReport }

/* ------------------------------------------------------------- Home --- */
export function HomePage({ onStart }: { onStart: () => void }) {
  return (
    <div className="hero">
      <h1>DevRepro Doctor</h1>
      <p className="tagline">
        Project-aware developer-environment diagnostics, reproducibility snapshots,
        machine-to-machine diffs and explainable safe remediation.
      </p>
      <ul className="hero-points">
        <li>Read-only by default — nothing is modified without explicit confirmation.</li>
        <li>Privacy-safe — usernames, home paths and secrets are redacted; exports are blocked if secrets are detected.</li>
        <li>No cloud, no telemetry — all data stays on your machine.</li>
      </ul>
      <button className="btn btn-primary" onClick={onStart}>Open machine overview →</button>
      <Card title="60-second CLI start">
        <pre>{`pip install devrepro-doctor
devrepro doctor
devrepro snapshot
devrepro diff A B`}</pre>
        <CopyButton text={`pip install devrepro-doctor
devrepro doctor`} label="Copy commands" />
      </Card>
    </div>
  )
}

/* ----------------------------------------------- Machine Overview --- */
export function OverviewPage({ report }: PageProps) {
  const counts = countByState(report.findings)
  return (
    <>
      <h2>Machine overview</h2>
      <div className="grid grid-4">
        <Stat label="OS" value={`${report.platform.os_name} ${report.platform.os_version}`} />
        <Stat label="Arch" value={report.platform.arch} />
        <Stat label="Tools detected" value={String(report.tools.length)} />
        <Stat label="Findings" value={String(report.findings.length)} />
      </div>
      <Card title="Finding states">
        <div className="badge-row">
          {Object.entries(counts).map(([s, n]) => (
            <span key={s}><Badge state={s} /> ×{n}</span>
          ))}
        </div>
      </Card>
      {report.score && <ScoreCard report={report} />}
      {report.probe_errors.length > 0 && (
        <Card title="Probe errors (non-fatal)">
          <ul>{report.probe_errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        </Card>
      )}
    </>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}

export function ScoreCard({ report }: PageProps) {
  const s = report.score!
  return (
    <Card title={`Reproducibility completeness: ${s.total}/${s.possible} (${s.percent}%)`}>
      <p className="muted">Describes how completely the project <em>declares</em> its environment. It does not guarantee reproducibility.</p>
      <table className="table">
        <thead><tr><th>Point</th><th>Earned</th><th>Why</th></tr></thead>
        <tbody>
          {s.points.map((p) => (
            <tr key={p.name}><td>{p.name}</td><td>{p.earned}/{p.possible}</td><td>{p.why}</td></tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

/* ------------------------------------------------ Project Readiness --- */
export function ReadinessPage({ report }: PageProps) {
  const blocking = report.findings.filter((f) => f.state === 'BLOCKED' || f.state === 'ERROR')
  const warnings = report.findings.filter((f) => f.state === 'WARN')
  const verdict = blocking.length ? 'BLOCKED' : warnings.length ? 'READY_WITH_WARNINGS' : 'READY'
  return (
    <>
      <h2>Project readiness</h2>
      <p>Preflight verdict: <Badge state={verdict} /></p>
      <Card title="Declared requirements">
        {report.requirements.length === 0 ? <EmptyState what="declared requirements" /> : (
          <table className="table">
            <thead><tr><th>Ecosystem</th><th>Name</th><th>Spec</th><th>Source</th></tr></thead>
            <tbody>
              {report.requirements.map((r, i) => (
                <tr key={i}><td>{r.ecosystem}</td><td>{r.name}</td><td><code>{r.spec}</code></td><td>{r.source_file}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title="Blockers">
        {blocking.length === 0 ? <EmptyState what="blockers" /> : (
          <ul>{blocking.map((f) => <li key={f.rule_id}><code>{f.rule_id}</code> — {f.summary}</li>)}</ul>
        )}
      </Card>
    </>
  )
}

/* ------------------------------------------------------ Toolchains --- */
export function ToolchainsPage({ report }: PageProps) {
  const [q, setQ] = useState('')
  const tools = report.tools.filter((t) => t.name.includes(q.toLowerCase()))
  return (
    <>
      <h2>Toolchains</h2>
      <input className="search" placeholder="Filter tools…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter tools" />
      {tools.length === 0 ? <EmptyState what="tools" /> : (
        <div className="grid grid-3">
          {tools.map((t, i) => (
            <Card key={i} title={t.name}>
              <p><strong>{t.version ?? 'version unknown'}</strong></p>
              <p className="mono small">{t.exe_path}</p>
              {t.install_source && <p className="muted small">source: {t.install_source}</p>}
            </Card>
          ))}
        </div>
      )}
    </>
  )
}

/* ---------------------------------------------------- PATH Explorer --- */
export function PathPage({ report }: PageProps) {
  const pa = report.path_analysis
  if (!pa) return <EmptyState what="PATH analysis" />
  return (
    <>
      <h2>PATH explorer</h2>
      <Card title="Precedence order (earlier wins)">
        <ol className="path-list">
          {pa.entries.map((e) => (
            <li key={e.index} className={!e.exists ? 'dead' : ''}>
              <span className="idx">#{e.index}</span> <code>{e.raw}</code>
              {!e.exists && <span className="badge badge-error">dead</span>}
              {pa.duplicates.includes(e.raw) && <span className="badge badge-warn">duplicate</span>}
            </li>
          ))}
        </ol>
      </Card>
      {pa.shadowed_executables.length > 0 && (
        <Card title="Shadowed executables">
          <table className="table">
            <thead><tr><th>Name</th><th>Winner</th><th>Shadowed</th></tr></thead>
            <tbody>
              {pa.shadowed_executables.map(([n, w, l], i) => (
                <tr key={i}><td>{n}</td><td><code>{w}</code></td><td><code>{l}</code></td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}

/* -------------------------------------------------------- Findings --- */
export function FindingsPage({ report }: PageProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set(['BLOCKED', 'ERROR', 'WARN']))
  const [q, setQ] = useState('')
  const toggle = (s: string) => {
    const next = new Set(selected)
    next.has(s) ? next.delete(s) : next.add(s)
    setSelected(next)
  }
  const findings = report.findings.filter(
    (f) => selected.has(f.state) && (!q || f.summary.toLowerCase().includes(q.toLowerCase()) || f.rule_id.includes(q)),
  )
  return (
    <>
      <h2>Findings</h2>
      <input className="search" placeholder="Search findings…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search findings" />
      <SeverityFilter selected={selected} onToggle={toggle} />
      {findings.length === 0 ? <EmptyState what="matching findings" /> : (
        <div className="findings-list">
          {findings.map((f) => (
            <article key={f.rule_id} className="card finding">
              <header>
                <Badge state={f.state} /> <code>{f.rule_id}</code>
                {f.component && <span className="muted"> · {f.component}</span>}
              </header>
              <p>{f.summary}</p>
              {(f.detected || f.required) && (
                <p className="small">detected: <code>{f.detected ?? '—'}</code> · required: <code>{f.required ?? '—'}</code></p>
              )}
              <EvidenceDrawer finding={f} />
            </article>
          ))}
        </div>
      )}
    </>
  )
}

/* -------------------------------------------------- Environment Diff --- */
export function DiffPage() {
  const [diff, setDiff] = useState<EnvironmentDiff | null>(null)
  const [err, setErr] = useState('')
  const load = async (file: File) => {
    try { setDiff(JSON.parse(await file.text()) as EnvironmentDiff); setErr('') }
    catch { setErr('Not a valid environment diff JSON export.') }
  }
  return (
    <>
      <h2>Environment diff</h2>
      <p className="muted">Load a diff JSON produced by <code>devrepro diff A B --format json -o diff.json</code>.</p>
      <input type="file" accept=".json" aria-label="Diff JSON file" onChange={(e) => e.target.files?.[0] && load(e.target.files[0])} />
      {err && <p role="alert">{err}</p>}
      {diff && (
        <table className="table">
          <thead><tr><th>Component</th><th>Name</th><th>Classification</th><th>A</th><th>B</th><th>Critical</th></tr></thead>
          <tbody>
            {diff.entries.map((e, i) => (
              <tr key={i} className={e.project_critical ? 'row-critical' : ''}>
                <td>{e.component}</td><td>{e.name}</td><td><Badge state={e.classification.toUpperCase()} /></td>
                <td><code>{e.a_value ?? '—'}</code></td><td><code>{e.b_value ?? '—'}</code></td>
                <td>{e.project_critical ? '⚠️' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

/* ------------------------------------------------------- Snapshots --- */
export function SnapshotsPage({ report }: PageProps) {
  return (
    <>
      <h2>Snapshots</h2>
      <Card title="Current snapshot metadata">
        <p>Schema: {report.schema_version} · DevRepro v{report.devrepro_version} · {report.created_at}</p>
        <p className="muted">Snapshots contain no usernames, home paths or secrets by default.</p>
        <CopyButton text={JSON.stringify(report, null, 2)} label="Copy snapshot JSON" />
      </Card>
      <Card title="Create / compare via CLI">
        <pre>{[
          '# create',
          'devrepro snapshot -o snap.json',
          '# compare two machines',
          'devrepro diff machineA.json machineB.json --format html -o diff.html',
        ].join(String.fromCharCode(10))}</pre>
      </Card>
    </>
  )
}

/* ----------------------------------------------------------- Rules --- */
export function RulesPage({ report }: PageProps) {
  const packs = useMemo(() => {
    const m = new Map<string, number>()
    for (const f of report.findings) m.set(f.rule_id.split('/')[0], (m.get(f.rule_id.split('/')[0]) ?? 0) + 1)
    return [...m.entries()].sort()
  }, [report])
  return (
    <>
      <h2>Rules</h2>
      <p className="muted">Rule packs observed in this report. Full catalog: <code>devrepro rules</code>.</p>
      <div className="grid grid-3">
        {packs.map(([pack, n]) => <Card key={pack} title={pack}><p>{n} finding(s)</p></Card>)}
      </div>
    </>
  )
}

/* ------------------------------------------------- Remediation Plan --- */
export function RemediationPage({ report }: PageProps) {
  const actionable = report.findings.filter((f) => f.remediation_hint && f.state !== 'PASS')
  return (
    <>
      <h2>Remediation plan</h2>
      <p className="muted">Dry-run only. DevRepro never executes MEDIUM/HIGH steps; SAFE/LOW steps require explicit confirmation.</p>
      {actionable.length === 0 ? <EmptyState what="actionable remediations" /> : (
        <div className="findings-list">
          {actionable.map((f) => (
            <article key={f.rule_id} className="card finding">
              <header><Badge state={f.state} /> <code>{f.rule_id}</code></header>
              <p>{f.remediation_hint}</p>
              <CopyButton text={f.remediation_hint!} label="Copy guidance" />
            </article>
          ))}
        </div>
      )}
    </>
  )
}

/* --------------------------------------------------------- History --- */
export function HistoryPage() {
  return (
    <>
      <h2>History</h2>
      <p className="muted">Local-only history lives in <code>~/.devrepro-doctor/history</code>. View drift with:</p>
      <pre>devrepro history --json</pre>
      <p>Drift kinds reported: runtime changed, Docker upgraded, compiler missing, PATH precedence changed, new blocker introduced.</p>
    </>
  )
}

/* ------------------------------------------------------------ Docs --- */
export function DocsPage() {
  return (
    <>
      <h2>Docs</h2>
      <Card title="CLI quick reference">
        <pre>{`devrepro doctor          # full read-only diagnostic scan
devrepro info            # quick machine summary
devrepro scan -o r.json  # emit a sanitized report artifact
devrepro project         # what does this project declare?
devrepro path            # analyze PATH health
devrepro which --all python
devrepro snapshot        # privacy-sanitized environment manifest
devrepro diff A B        # explain "works on my machine"
devrepro preflight       # CI gate: READY / READY_WITH_WARNINGS / BLOCKED
devrepro plan            # dry-run safe remediation plan
devrepro fix --yes       # execute ONLY SAFE/LOW automatable steps
devrepro rules           # list rule packs
devrepro plugins         # list installed plugins
devrepro report r.json --format html
devrepro export r.json --out-dir out/
devrepro history         # local drift since previous snapshot
devrepro serve           # localhost-only UI + API
devrepro self-test`}</pre>
      </Card>
      <Card title="Policy example (.devrepro.toml)">
        <pre>{`[supported_os]
linux = true

[required_runtimes]
python = ">=3.11,<3.14"

[required_tools]
git = "*"

[required_env_names]
names = ["GITHUB_TOKEN"]`}</pre>
      </Card>
    </>
  )
}

/* --------------------------------------------------- Contributors --- */
export function ContributorsPage() {
  return (
    <>
      <h2>Contributors</h2>
      <Card title="Creator / Lead Maintainer">
        <p><strong>@webdevsamran</strong> — original creator, founder and lead maintainer of DevRepro Doctor.</p>
      </Card>
      <Card title="Join the project">
        <p>See CONTRIBUTING.md for setup, plugin authoring guides and good first issues.</p>
      </Card>
    </>
  )
}

/* ---------------------------------------------------------- About --- */
export function AboutPage({ report }: PageProps) {
  return (
    <>
      <h2>About</h2>
      <Card title="Privacy promise">
        <ul>
          <li>Default behavior is read-only.</li>
          <li>Usernames, home directories, emails, tokens and API keys are redacted.</li>
          <li>Exports containing probable secrets are blocked entirely.</li>
          <li>No telemetry. No cloud upload. Ever.</li>
        </ul>
        <p>Report privacy flags: <code>{JSON.stringify(report.privacy)}</code></p>
      </Card>
      <Card title="License & attribution">
        <p>Apache-2.0. Created and maintained by <strong>@webdevsamran</strong>.</p>
      </Card>
    </>
  )
}

/* ---------------------------------------------------------- utils --- */
function countByState(findings: { state: string }[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of findings) out[f.state] = (out[f.state] ?? 0) + 1
  return out
}