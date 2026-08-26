/**
 * Wave-3/4/7 capability pages: profile/maturity, baseline, env vars,
 * ports/services, git health, network/TLS and the fleet dashboard.
 * All data is sanitized; fleet fixtures must be labelled DEMO.
 */
import {
  loadBaseline, loadEnv, loadFleet, loadGitHealth, loadNetwork, loadPorts,
  loadProfile, useAsync,
  type BaselineDiffEntry, type EnvReport, type FleetDashboard,
  type GitHealth, type NetworkReport, type PortsReport, type ProfilePayload,
} from '../api/capabilities'
import { Card, EmptyState } from '../components/ui'

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <h2>{title}</h2>
      {children}
    </>
  )
}

function Async<T>({ fn, render }: { fn: () => Promise<T>; render: (d: T) => React.ReactNode }) {
  const { data, error } = useAsync(fn)
  if (error) return <Card title="Data unavailable"><p className="muted">{error}</p><p className="muted">Run the matching CLI command to generate this artifact (e.g. <code>devrepro profile</code>) or serve it via <code>devrepro serve</code>.</p></Card>
  if (!data) return <div className="skeleton" aria-busy="true" aria-label="Loading" />
  return <>{render(data)}</>
}

/* ------------------------------------------------- Profile / Maturity --- */
export function ProfilePage() {
  return (
    <Page title="Readiness profile & maturity">
      <Async fn={loadProfile} render={(d: ProfilePayload) => (
        <>
          <div className="grid grid-3">
            <div className="stat card"><div className="stat-label">Profile</div><div className="stat-value">{d.profile}</div></div>
            <div className="stat card"><div className="stat-label">Confidence</div><div className="stat-value">{Math.round(d.confidence * 100)}%</div></div>
            <div className="stat card"><div className="stat-label">Maturity</div><div className="stat-value">{d.maturity.percent}%</div></div>
          </div>
          <Card title={`Declaration completeness ${d.maturity.total}/${d.maturity.possible}`}>
            <table className="table">
              <thead><tr><th>Factor</th><th>Earned</th><th>Evidence</th></tr></thead>
              <tbody>
                {d.maturity.factors.map((f) => (
                  <tr key={f.name}>
                    <td>{f.earned >= f.weight ? '✅' : '❌'} {f.name}</td>
                    <td>{f.earned}/{f.weight}</td>
                    <td>{f.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">Measures how completely the environment is declared; it does not guarantee identical builds.</p>
          </Card>
          <Card title="Detection signals"><ul>{d.signals.map((s) => <li key={s}>{s}</li>)}</ul></Card>
        </>
      )} />
    </Page>
  )
}

/* -------------------------------------------------------- Baseline --- */
export function BaselinePage() {
  return (
    <Page title="Baseline compliance">
      <p className="muted">Machine vs approved project baseline (<code>devrepro baseline create|diff</code>).</p>
      <Async fn={loadBaseline} render={(d: { baseline_id: string; entries: BaselineDiffEntry[] }) => (
        <>
          <p>Baseline <code>{d.baseline_id}</code></p>
          {d.entries.length === 0 ? <EmptyState what="baseline entries" /> : (
            <table className="table">
              <thead><tr><th>Severity</th><th>Tool</th><th>Expected</th><th>Actual</th><th>Impact</th></tr></thead>
              <tbody>
                {d.entries.map((e) => (
                  <tr key={e.name}>
                    <td><span className={`sev sev-${e.severity}`}>{e.severity}</span></td>
                    <td>{e.name}</td><td><code>{e.expected}</code></td><td><code>{e.actual}</code></td>
                    <td>{e.project_impact}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )} />
    </Page>
  )
}

/* ------------------------------------------------------ Env vars --- */
export function EnvVarsPage() {
  return (
    <Page title="Environment variables">
      <p className="muted">Names and declaration status only — values are never displayed.</p>
      <Async fn={loadEnv} render={(d: EnvReport) => (
        <>
          {!d.ok && <p><span className="sev sev-warn">policy gaps detected</span></p>}
          <Card title="Declared origins">
            {d.origins.length === 0 ? <EmptyState what="env-var declarations" /> : (
              <table className="table">
                <thead><tr><th>Name</th><th>Source</th><th>Kind</th><th>Value in file?</th></tr></thead>
                <tbody>{d.origins.map((o) => (
                  <tr key={o.name + o.source}><td><code>{o.name}</code></td><td>{o.source}</td><td>{o.kind}</td><td>{o.has_value ? 'yes' : 'no'}</td></tr>
                ))}</tbody>
              </table>
            )}
          </Card>
          {(d.missing_required.length > 0 || d.forbidden_present.length > 0 || Object.keys(d.duplicated).length > 0) && (
            <Card title="Policy findings">
              <ul>
                {d.missing_required.map((n) => <li key={n}>missing required: <code>{n}</code></li>)}
                {d.forbidden_present.map((n) => <li key={n}>forbidden present: <code>{n}</code></li>)}
                {Object.entries(d.duplicated).map(([n, srcs]) => <li key={n}>duplicated: <code>{n}</code> in {srcs.join(', ')}</li>)}
              </ul>
            </Card>
          )}
          {d.dotenv_findings.length > 0 && (
            <Card title="Dotnet/dotenv safety">
              <ul>{d.dotenv_findings.map((f, i) => <li key={i}><span className={`sev sev-${f.severity}`}>{f.severity}</span> {f.path}: {f.detail}</li>)}</ul>
            </Card>
          )}
        </>
      )} />
    </Page>
  )
}

/* ------------------------------------------------ Ports / services --- */
export function ServicesPage() {
  return (
    <Page title="Ports & local services">
      <Async fn={loadPorts} render={(d: PortsReport) => (
        <>
          <Card title="Declared ports">
            {d.declared_ports.length === 0 ? <EmptyState what="port declarations" /> : (
              <table className="table">
                <thead><tr><th>Port</th><th>Service</th><th>Source</th></tr></thead>
                <tbody>{d.declared_ports.map((p, i) => (
                  <tr key={i}><td>{p.port}</td><td>{p.service}</td><td>{p.source}</td></tr>
                ))}</tbody>
              </table>
            )}
          </Card>
          {d.conflicts.length > 0 && (
            <Card title="Port conflicts">
              <ul>{d.conflicts.map((c, i) => <li key={i}><span className="sev sev-blocker">conflict</span> port {c.port} ({c.service}) is in use</li>)}</ul>
            </Card>
          )}
          <Card title="Inferred dev services">
            {Object.keys(d.inferred_services).length === 0 ? <EmptyState what="inferred services" /> : (
              <ul>{Object.entries(d.inferred_services).map(([name, s]) => <li key={name}>{name}: {s.host}:{s.port}</li>)}</ul>
            )}
          </Card>
          {d.probes && d.probes.length > 0 && (
            <Card title="TCP probes (--probe)">
              <ul>{d.probes.map((p, i) => <li key={i}>{p.service} {p.host}:{p.port} — {p.reachable ? 'reachable' : `unreachable (${p.detail})`}</li>)}</ul>
            </Card>
          )}
        </>
      )} />
    </Page>
  )
}

/* ---------------------------------------------------- Git health --- */
export function GitHealthPage() {
  return (
    <Page title="Git health">
      <Async fn={loadGitHealth} render={(d: GitHealth) => (
        <>
          {!d.is_repo && <p><span className="sev sev-blocker">not a git repository</span></p>}
          <div className="grid grid-4">
            <div className="stat card"><div className="stat-label">Signing configured</div><div className="stat-value">{d.signing_configured ? 'yes' : 'no'}</div></div>
            <div className="stat card"><div className="stat-label">Credential helper</div><div className="stat-value">{d.credential_helper_present ? 'present' : 'none'}</div></div>
            <div className="stat card"><div className="stat-label">Git LFS</div><div className="stat-value">{d.lfs_available ? 'available' : 'absent'}</div></div>
            <div className="stat card"><div className="stat-label">Linked worktree</div><div className="stat-value">{d.linked_worktree ? 'yes' : 'no'}</div></div>
          </div>
          <Card title="Relevant config (credential-safe)">
            <table className="table"><tbody>
              {Object.entries(d.config).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}
            </tbody></table>
          </Card>
          {d.submodules.length > 0 && (
            <Card title="Submodules">
              <table className="table">
                <thead><tr><th>Path</th><th>Initialized</th><th>Clean</th></tr></thead>
                <tbody>{d.submodules.map((s) => (
                  <tr key={s.path}><td>{s.path}</td><td>{s.initialized ? '✅' : '❌'}</td><td>{!s.dirty ? '✅' : '⚠️ dirty'}</td></tr>
                ))}</tbody>
              </table>
            </Card>
          )}
          {d.notes.length > 0 && <Card title="Notes"><ul>{d.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></Card>}
        </>
      )} />
    </Page>
  )
}

/* -------------------------------------------------- Network / TLS --- */
export function NetworkTlsPage() {
  return (
    <Page title="Network & TLS">
      <Async fn={loadNetwork} render={(d: NetworkReport) => (
        <>
          <Card title="Clock sanity">
            <p>Skew: {d.clock.skew_seconds}s — {d.clock.plausible ? 'plausible' : 'SUSPICIOUS (certificate/token workflows may fail)'}</p>
            <p className="muted">{d.clock.detail}</p>
          </Card>
          <Card title="Proxy chain">
            <table className="table"><tbody>
              {Object.entries(d.proxy.env).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>)}
              <tr><td>git http.proxy</td><td>{d.proxy.git_proxy ?? 'not set'}</td></tr>
            </tbody></table>
          </Card>
          {d.tls && d.tls.length > 0 && (
            <Card title="TLS checks (opt-in)">
              <ul>{d.tls.map((t, i) => <li key={i}>{t.host}: {t.ok ? 'ok' : t.classification} — {t.detail}</li>)}</ul>
            </Card>
          )}
          {d.registries && d.registries.length > 0 && (
            <Card title="Registry reachability (opt-in)">
              <ul>{d.registries.map((r, i) => <li key={i}>{r.name}: {r.reachable ? 'reachable' : r.detail}</li>)}</ul>
            </Card>
          )}
        </>
      )} />
    </Page>
  )
}

/* --------------------------------------------- Fleet dashboard --- */
const DEMO_FLEET: FleetDashboard = {
  machines: [
    { machine_key: 'demo-laptop-win', os_name: 'Windows', arch: 'x86_64', verdict: 'ready', tools: { python: '3.12.1', node: '20.11.0' }, label: 'DEMO' },
    { machine_key: 'demo-ci-linux', os_name: 'Linux', arch: 'x86_64', verdict: 'ready_with_warnings', tools: { python: '3.11.9', node: '18.19.1' }, label: 'DEMO' },
    { machine_key: 'demo-mac-arm', os_name: 'macOS', arch: 'aarch64', verdict: 'blocked', tools: { python: '3.10.14' }, label: 'DEMO' },
  ],
  readiness_distribution: { ready: 1, ready_with_warnings: 1, blocked: 1 },
  segmentation: [
    { os: 'Linux', arch: 'x86_64', verdict: 'ready_with_warnings', machines: 1 },
    { os: 'macOS', arch: 'aarch64', verdict: 'blocked', machines: 1 },
    { os: 'Windows', arch: 'x86_64', verdict: 'ready', machines: 1 },
  ],
  heatmap: {
    python: { '3.12.1': 1, '3.11.9': 1, '3.10.14': 1 },
    node: { '20.11.0': 1, '18.19.1': 1, absent: 1 },
  },
}

export function FleetDashboardPage() {
  const { data, error } = useAsync(loadFleet)
  // No live fleet API? Show clearly-labelled DEMO fixture instead of an error.
  const dash = data ?? (error ? DEMO_FLEET : null)
  if (!dash) return <div className="skeleton" aria-busy="true" />
  return (
    <Page title="Fleet dashboard">
      {!data && <p><span className="sev sev-warn">DEMO DATA</span> — no self-hosted fleet API reachable; showing a synthetic fixture.</p>}
      <div className="grid grid-4">
        {Object.entries(dash.readiness_distribution).map(([verdict, n]) => (
          <div key={verdict} className="stat card">
            <div className="stat-label">{verdict.replace(/_/g, ' ')}</div>
            <div className="stat-value">{n}</div>
          </div>
        ))}
      </div>
      <Card title="OS / architecture mix">
        <table className="table">
          <thead><tr><th>OS</th><th>Arch</th><th>Verdict</th><th>Machines</th></tr></thead>
          <tbody>{dash.segmentation.map((s, i) => (
            <tr key={i}><td>{s.os}</td><td>{s.arch}</td><td>{s.verdict}</td><td>{s.machines}</td></tr>
          ))}</tbody>
        </table>
      </Card>
      <Card title="Tool-version heatmap">
        <table className="table">
          <thead><tr><th>Tool</th><th>Versions observed</th></tr></thead>
          <tbody>{Object.entries(dash.heatmap).map(([tool, versions]) => (
            <tr key={tool}><td>{tool}</td><td>{Object.entries(versions).map(([v, n]) => `${v} ×${n}`).join(' · ')}</td></tr>
          ))}</tbody>
        </table>
      </Card>
      {dash.compliance && dash.compliance.length > 0 && (
        <Card title="Baseline compliance">
          <table className="table">
            <thead><tr><th>Machine</th><th>Status</th><th>Failures</th></tr></thead>
            <tbody>{dash.compliance.map((c) => (
              <tr key={c.machine_key}>
                <td>{c.machine_key}</td>
                <td>{c.compliant ? '✅ compliant' : '❌ non-compliant'}</td>
                <td>{c.failures.map((f) => `${f.tool}: expected ${f.expected}, got ${f.actual}`).join('; ') || '—'}</td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}
    </Page>
  )
}