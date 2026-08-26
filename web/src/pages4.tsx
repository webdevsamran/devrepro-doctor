/**
 * Enterprise console pages (self-hosted fleet service):
 * audit log, policy exceptions, agents/enrollment, retention and server
 * settings. Data comes from the versioned fleet API when served; otherwise
 * clearly-labelled DEMO fixtures are shown.
 */
import { loadAgents, loadAuditLog, loadExceptions, loadRetention } from './api3'
import { AsyncDemo } from './pages3'
import { Card, EmptyState } from './components'

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <h2>{title}</h2>
      {children}
    </>
  )
}

/* ---------------------------------------------------------- Audit log --- */
export function AuditLogPage() {
  return (
    <Page title="Audit log">
      <p className="muted">Immutable events for policy changes, approvals, enrollment and snapshot publication.</p>
      <AsyncDemo fn={loadAuditLog} render={(events) => (
        <table className="table">
          <thead><tr><th>#</th><th>When</th><th>Actor</th><th>Action</th><th>Target</th></tr></thead>
          <tbody>{events.map((e) => (
            <tr key={e.id}>
              <td>{e.id}</td>
              <td><time dateTime={e.created_at}>{new Date(e.created_at).toLocaleString()}</time></td>
              <td><code>{e.actor}</code></td>
              <td><span className="badge">{e.action}</span></td>
              <td>{e.target}</td>
            </tr>
          ))}</tbody>
        </table>
      )} />
    </Page>
  )
}

/* --------------------------------------------------------- Exceptions --- */
export function ExceptionsPage() {
  return (
    <Page title="Policy exceptions">
      <p className="muted">Exception requests carry an expiry, justification and reviewer. Expired or unreviewed exceptions grant nothing.</p>
      <AsyncDemo fn={loadExceptions} render={(items) => (
        items.length === 0 ? <EmptyState what="exception requests" /> : (
          <table className="table">
            <thead><tr><th>Policy</th><th>Justification</th><th>Expires</th><th>Reviewer</th><th>Status</th></tr></thead>
            <tbody>{items.map((x) => (
              <tr key={x.id}>
                <td><code>{x.policy}</code></td>
                <td>{x.justification}</td>
                <td><time dateTime={x.expires_at}>{new Date(x.expires_at).toLocaleDateString()}</time></td>
                <td>{x.reviewer ?? '—'}</td>
                <td>{x.approved
                  ? <span className="sev sev-ok">approved</span>
                  : <span className="sev sev-warn">pending review</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )
      )} />
    </Page>
  )
}

/* --------------------------------------------- Agents / enrollment ------ */
export function AgentsEnrollmentPage() {
  return (
    <Page title="Agents & enrollment">
      <p className="muted">Machines enrolled with single-use tokens; snapshots are sanitized-only at ingestion. Agent mode is opt-in with an explicit outbound endpoint.</p>
      <AsyncDemo fn={loadAgents} render={(rows) => (
        <>
          <p className="muted">Enrollment CLI: <code>devrepro enroll --server https://fleet.example.com --token &lt;one-time-token&gt;</code></p>
          <table className="table">
            <thead><tr><th>Machine</th><th>OS</th><th>Arch</th><th>Last snapshot</th><th>Readiness</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.machine_key}>
                <td><code>{r.machine_key}</code></td>
                <td>{r.os_name}</td>
                <td>{r.arch}</td>
                <td>{r.last_snapshot ? new Date(r.last_snapshot).toLocaleString() : 'never'}</td>
                <td><span className={`sev sev-${r.readiness === 'BLOCKED' ? 'blocker' : r.readiness === 'READY' ? 'ok' : 'warn'}`}>{r.readiness}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </>
      )} />
    </Page>
  )
}

/* ------------------------------------------------------------ Retention - */
export function RetentionPage() {
  return (
    <Page title="Retention">
      <p className="muted">Snapshots and audit events are deleted on schedule; deletion itself is audited.</p>
      <AsyncDemo fn={loadRetention} render={(cfg) => (
        <Card title="Configured windows">
          <ul>
            <li>Snapshots older than <strong>{cfg.snapshot_days} days</strong> are removed.</li>
            <li>Audit events older than <strong>{cfg.audit_days} days</strong> are removed.</li>
          </ul>
          <p className="muted">Server-side apply: <code>POST /api/v1/retention/apply</code>.</p>
        </Card>
      )} />
    </Page>
  )
}

/* ------------------------------------------------------ Server settings - */
export function ServerSettingsPage() {
  return (
    <Page title="Server health & settings">
      <div className="grid grid-3">
        <div className="stat card"><div className="stat-label">Status</div><div className="stat-value">healthy</div></div>
        <div className="stat card"><div className="stat-label">API</div><div className="stat-value">v1</div></div>
        <div className="stat card"><div className="stat-label">Auth methods</div><div className="stat-value">3</div></div>
      </div>
      <Card title="Endpoints">
        <ul>
          <li>Health: <code>GET /healthz</code> · readiness: <code>GET /api/v1/health</code></li>
          <li>Metrics: <code>GET /metrics</code> (Prometheus format)</li>
          <li>OpenAPI: <code>GET /api/v1/openapi.json</code></li>
          <li>Backup: <code>devrepro server-backup &lt;db&gt;</code> · restore: <code>devrepro server-restore</code></li>
        </ul>
      </Card>
      <Card title="Authentication">
        <p>Local service accounts are always available. OIDC claim→RBAC mapping and SAML metadata parsing ship built-in; connect a real IdP by configuration only (<code>docs/SERVER.md</code>). External IdP conformance is not asserted from CI.</p>
      </Card>
    </Page>
  )
}
