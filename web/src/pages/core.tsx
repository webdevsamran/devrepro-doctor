import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { MeterRow, ScoreRadial, StackedBar } from '../components/charts'
import { scorePercent } from '../types'
import type { Finding, ScanReport } from '../types'
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
        <pre tabIndex={0}>{`pip install git+https://github.com/webdevsamran/devrepro-doctor
devrepro doctor
devrepro snapshot
devrepro diff A B`}</pre>
        <CopyButton text={`pip install git+https://github.com/webdevsamran/devrepro-doctor
devrepro doctor`} label="Copy commands" />
      </Card>
    </div>
  )
}

/* ----------------------------------------------- Machine Overview --- */
/** Severity order and colour, taken from the same tokens the badges use so a
 *  chart and a badge can never disagree about what WARN looks like. */
const SEVERITY_ORDER = ['BLOCKED', 'ERROR', 'WARN', 'UNKNOWN', 'INFO', 'PASS'] as const
const SEVERITY_COLOR: Record<string, string> = {
  BLOCKED: 'var(--sev-blocked)',
  ERROR: 'var(--sev-error)',
  WARN: 'var(--sev-warn)',
  UNKNOWN: 'var(--sev-unknown)',
  INFO: 'var(--sev-info)',
  PASS: 'var(--sev-pass)',
}

export function OverviewPage({ report }: PageProps) {
  const counts = countByState(report.findings)
  const blockers = report.findings.filter((f) => f.state === 'BLOCKED' || f.state === 'ERROR')
  const segments = SEVERITY_ORDER.filter((s) => counts[s]).map((s) => ({
    key: s,
    label: s,
    value: counts[s],
    color: SEVERITY_COLOR[s],
  }))

  return (
    <>
      <h2>Machine overview</h2>
      <div className="grid grid-4 enter">
        <Stat label="OS" value={`${report.platform.os_name} ${report.platform.os_version}`} />
        <Stat label="Arch" value={report.platform.arch} />
        <Stat label="Tools detected" value={String(report.tools.length)} />
        <Stat label="Findings" value={String(report.findings.length)} />
      </div>

      <div className="grid grid-2 enter enter-1">
        {report.score && (
          <Card title="Reproducibility" hint="How completely this project declares its environment.">
            <div className="row" style={{ gap: 'var(--sp-5)', alignItems: 'center' }}>
              <ScoreRadial
                value={report.score.total}
                max={report.score.possible}
                label={`${scorePercent(report.score)}% declared`}
              />
              <div className="stack" style={{ flex: 1, minWidth: '10rem' }}>
                {report.score.points.map((pt) => (
                  <MeterRow
                    key={pt.criterion}
                    label={pt.criterion}
                    value={pt.earned}
                    max={pt.possible}
                    hint={`${pt.earned}/${pt.possible}`}
                    color={pt.earned === pt.possible ? 'var(--sev-pass)' : 'var(--sev-warn)'}
                  />
                ))}
              </div>
            </div>
          </Card>
        )}

        <Card title="Findings by severity" hint={`${report.findings.length} in this scan.`}>
          <StackedBar segments={segments} />
          <div className="mt-4">
            {blockers.length === 0 ? (
              <p className="small muted mb-0">Nothing is blocking a build on this machine.</p>
            ) : (
              <>
                <h4>Blocking now</h4>
                <ul className="stack" style={{ paddingLeft: '1.1rem', gap: 'var(--sp-1)' }}>
                  {blockers.slice(0, 5).map((f) => (
                    <li key={f.rule_id} className="small">
                      <code>{f.rule_id}</code> — {f.summary}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </Card>
      </div>

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
    <Card title={`Reproducibility completeness: ${s.total}/${s.possible} (${scorePercent(s)}%)`}>
      <p className="muted">Describes how completely the project <em>declares</em> its environment. It does not guarantee reproducibility.</p>
      <table className="table">
        <thead><tr><th>Point</th><th>Earned</th><th>Why</th></tr></thead>
        <tbody>
          {s.points.map((p) => (
            <tr key={p.criterion}>
              <td className="mono">{p.criterion}</td>
              <td className="num">{p.earned}/{p.possible}</td>
              <td>{p.explanation}</td>
            </tr>
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
const SEVERITY_RANK: Record<string, number> = {
  BLOCKED: 0,
  ERROR: 1,
  WARN: 2,
  UNKNOWN: 3,
  INFO: 4,
  PASS: 5,
}

/** A stable, unique key for a finding.
 *
 *  Rule ids are NOT unique within a report: `env/credential-names-present` is
 *  emitted twice by a single scan, and `node/missing` covers both node and git
 *  because the composed prefix is the pack rather than the component. Keying a
 *  list by rule id gives React duplicate keys, which misassociates component
 *  state -- an open evidence drawer jumps to a different finding.
 */
export function findingKey(finding: Finding, index: number): string {
  return `${finding.rule_id}::${finding.component ?? ''}::${index}`
}

function findingsToMarkdown(findings: Finding[]): string {
  const NL = String.fromCharCode(10)
  const rows = findings.map(
    (f) =>
      `| ${f.state} | \`${f.rule_id}\` | ${f.summary.replace(/\|/g, '\\|')} |`,
  )
  return [
    '| State | Rule | Summary |',
    '|---|---|---|',
    ...rows,
    '',
    '_Produced by `devrepro doctor`. Read-only scan; output is privacy-redacted._',
  ].join(NL)
}

export function FindingsPage({ report }: PageProps) {
  // Filter state lives in the URL so a triage view can be linked to. "Look at
  // this" is most of what anyone does with a findings list, and a link that
  // reopens someone else's filters is the difference between sharing a view
  // and describing one.
  const [params, setParams] = useSearchParams()

  const activeStates = useMemo(() => {
    const raw = params.get('state')
    return new Set(raw ? raw.split(',').filter(Boolean) : ['BLOCKED', 'ERROR', 'WARN'])
  }, [params])

  const query = params.get('q') ?? ''
  const groupBy = params.get('group') ?? 'none'

  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  const toggle = (state: string) => {
    const next = new Set(activeStates)
    if (next.has(state)) next.delete(state)
    else next.add(state)
    update('state', [...next].join(','))
  }

  const counts = useMemo(() => {
    const tally: Record<string, number> = {}
    for (const f of report.findings) tally[f.state] = (tally[f.state] ?? 0) + 1
    return tally
  }, [report.findings])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return report.findings
      .filter((f) => activeStates.has(f.state))
      .filter(
        (f) =>
          !needle ||
          f.summary.toLowerCase().includes(needle) ||
          f.rule_id.toLowerCase().includes(needle) ||
          (f.component ?? '').toLowerCase().includes(needle),
      )
      .slice()
      .sort(
        (a, b) =>
          (SEVERITY_RANK[a.state] ?? 9) - (SEVERITY_RANK[b.state] ?? 9) ||
          a.rule_id.localeCompare(b.rule_id),
      )
  }, [report.findings, activeStates, query])

  const groups = useMemo(() => {
    if (groupBy === 'none') return [['', visible] as const]
    const buckets = new Map<string, Finding[]>()
    for (const f of visible) {
      const key =
        groupBy === 'component'
          ? (f.component ?? 'uncategorised')
          : groupBy === 'state'
            ? f.state
            : f.rule_id.split('/')[0]
      const bucket = buckets.get(key)
      if (bucket) bucket.push(f)
      else buckets.set(key, [f])
    }
    return [...buckets.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [visible, groupBy])

  return (
    <>
      <div className="row-between">
        <h2 className="mb-0">Findings</h2>
        <div className="row">
          <CopyButton text={findingsToMarkdown(visible)} label="Copy as Markdown" />
        </div>
      </div>

      <div className="card enter">
        <input
          className="input"
          placeholder="Search rule, summary or component…"
          value={query}
          onChange={(e) => update('q', e.target.value)}
          aria-label="Search findings"
        />
        <div className="row mt-4">
          <SeverityFilter selected={activeStates} counts={counts} onToggle={toggle} />
          <div className="spacer" />
          <label className="row small muted" style={{ gap: 'var(--sp-2)' }}>
            Group by
            <select
              className="input"
              style={{ width: 'auto' }}
              value={groupBy}
              onChange={(e) => update('group', e.target.value)}
            >
              <option value="none">nothing</option>
              <option value="state">severity</option>
              <option value="component">component</option>
              <option value="pack">rule prefix</option>
            </select>
          </label>
        </div>
        <p className="tiny subtle mt-4 mb-0">
          Showing {visible.length} of {report.findings.length}. Filters are in the URL, so
          this view can be linked to.
        </p>
      </div>

      {visible.length === 0 ? (
        <EmptyState
          what="matching findings"
          hint="Every severity may be filtered out — check the chips above."
        />
      ) : (
        groups.map(([groupName, items]) => (
          <section key={groupName || 'all'}>
            {groupName && (
              <h3 className="mt-4">
                {groupName} <span className="subtle small">({items.length})</span>
              </h3>
            )}
            {items.map((f, index) => (
              <article key={findingKey(f, index)} className="card finding enter">
                <header className="row">
                  <Badge state={f.state} />
                  <code>{f.rule_id}</code>
                  {f.component && <span className="muted small">· {f.component}</span>}
                </header>
                <p className="mb-0">{f.summary}</p>
                {(f.detected || f.required) && (
                  <p className="small muted">
                    detected <code>{f.detected ?? '—'}</code> · required{' '}
                    <code>{f.required ?? '—'}</code>
                  </p>
                )}
                <EvidenceDrawer finding={f} />
              </article>
            ))}
          </section>
        ))
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
        <pre tabIndex={0}>{[
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
      <pre tabIndex={0}>devrepro history --json</pre>
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
        <pre tabIndex={0}>{`devrepro doctor          # full read-only diagnostic scan
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
        <pre tabIndex={0}>{`[supported_os]
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