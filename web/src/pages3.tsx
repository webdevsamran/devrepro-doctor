/**
 * Wave-11 pages: shell startup, containers/WSL, GPU/AI stack, drift timeline,
 * generated environment preview and the plugin catalog. Enterprise console
 * pages live in pages4.tsx. Demo fallbacks always show a visible DEMO banner.
 */
import { useState } from 'react'
import {
  loadContainersWsl, loadDriftTimeline, loadGeneratedEnv, loadGpuAi,
  loadPlugins, loadShellStartup, useAsync2, type WithDemo,
} from './api3'
import { Card, EmptyState } from './components'

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <h2>{title}</h2>
      {children}
    </>
  )
}

export function DemoBanner() {
  return (
    <p className="badge badge-warn" role="note">
      DEMO DATA — no live report found. Run the matching CLI command or{' '}
      <code>devrepro serve</code> for real values.
    </p>
  )
}

/** Async wrapper with demo-aware fallback. */
export function AsyncDemo<T>({ fn, render }: {
  fn: () => Promise<WithDemo<T>>
  render: (d: T) => React.ReactNode
}) {
  const { result, error } = useAsync2(fn)
  if (error) {
    return (
      <Card title="Data unavailable">
        <p className="muted">{error}</p>
      </Card>
    )
  }
  if (!result) return <div className="skeleton" aria-busy="true" aria-label="Loading" />
  return (
    <>
      {result.demo && <DemoBanner />}
      {render(result.data as T)}
    </>
  )
}

export function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="btn"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? 'Copied!' : 'Copy'}
    </button>
  )
}

/* ------------------------------------------------------ Shell startup --- */
export function ShellStartupPage() {
  return (
    <Page title="Shell startup profile">
      <p className="muted">Slow profile scripts and expensive hooks. Secret contents are never displayed (<code>devrepro scan</code>).</p>
      <AsyncDemo fn={loadShellStartup} render={(d) => (
        <>
          <div className="grid grid-3">
            <div className="stat card"><div className="stat-label">Shell</div><div className="stat-value">{d.shell}</div></div>
            <div className="stat card"><div className="stat-label">Total startup</div><div className="stat-value">{d.total_ms} ms</div></div>
            <div className="stat card"><div className="stat-label">Segments</div><div className="stat-value">{d.segments.length}</div></div>
          </div>
          <Card title="Time by segment">
            {d.segments.map((s) => (
              <div key={s.script} style={{ marginBottom: '0.5rem' }}>
                <div className="muted">{s.script}{s.note ? ` — ${s.note}` : ''}</div>
                <div className="meter" role="img" aria-label={`${s.script}: ${s.ms} milliseconds`}>
                  <div className="meter-fill" style={{ width: `${Math.min(100, (s.ms / Math.max(d.total_ms, 1)) * 100)}%` }} />
                </div>
                <small>{s.ms} ms</small>
              </div>
            ))}
          </Card>
        </>
      )} />
    </Page>
  )
}

/* --------------------------------------------------- Containers / WSL --- */
export function ContainersWslPage() {
  return (
    <Page title="Containers & WSL">
      <AsyncDemo fn={loadContainersWsl} render={(d) => (
        <>
          <div className="grid grid-3">
            <Card title="Docker">
              {d.docker.error
                ? <span className="sev sev-blocker">unavailable</span>
                : <><code>{d.docker.server_version ?? '?'}</code> server</>}
              <ul>
                <li>Compose: {d.docker.compose ? 'yes' : 'no'}</li>
                <li>BuildKit: {d.docker.buildkit ? 'enabled' : 'disabled'}</li>
                {(d.docker.contexts ?? []).map((c) => <li key={c}>context: {c}</li>)}
              </ul>
            </Card>
            <Card title="Podman">
              {d.podman?.version
                ? <ul><li><code>{d.podman.version}</code></li><li>docker-compat: {d.podman.docker_compatible ? 'yes' : 'no'}</li></ul>
                : <EmptyState what="Podman installation" />}
            </Card>
            <Card title="WSL">
              {d.wsl.available ? (
                <ul>
                  {d.wsl.kernel && <li>kernel: <code>{d.wsl.kernel}</code></li>}
                  {d.wsl.distros.map((x) => (
                    <li key={x.name}>{x.name} — {x.state}, WSL{x.version}</li>
                  ))}
                </ul>
              ) : <EmptyState what="WSL distributions" />}
            </Card>
          </div>
          <Card title="Guidance"><ul>{d.guidance.map((g) => <li key={g}>{g}</li>)}</ul></Card>
        </>
      )} />
    </Page>
  )
}

/* -------------------------------------------------------- GPU/AI stack -- */
export function GpuAiStackPage() {
  return (
    <Page title="GPU / AI stack">
      <p className="muted">Driver/toolkit/runtime compatibility and framework backends. No models are downloaded.</p>
      <AsyncDemo fn={loadGpuAi} render={(d) => (
        <>
          <Card title="GPUs">
            {d.gpus.length === 0 ? <EmptyState what="GPU devices" /> : (
              <table className="table">
                <thead><tr><th>Device</th><th>Vendor</th><th>Driver</th><th>VRAM</th></tr></thead>
                <tbody>{d.gpus.map((g) => (
                  <tr key={g.name}><td>{g.name}</td><td>{g.vendor}</td><td>{g.driver ?? '—'}</td><td>{g.vram_gb != null ? `${g.vram_gb} GB` : '—'}</td></tr>
                ))}</tbody>
              </table>
            )}
          </Card>
          <div className="grid grid-3">
            <Card title="CUDA"><p>{d.cuda ? <>driver {d.cuda.driver ?? '?'} · toolkit {d.cuda.toolkit ?? '?'} · runtime {d.cuda.runtime ?? '?'}</> : 'not present'}</p></Card>
            <Card title="ROCm"><p>{d.rocm?.version ?? 'not present'}</p></Card>
            <Card title="Frameworks">
              <table className="table"><tbody>{d.frameworks.map((f) => (
                <tr key={f.name}><td>{f.name}</td><td><code>{f.version}</code></td><td>{f.backend}</td></tr>
              ))}</tbody></table>
            </Card>
          </div>
          <Card title="Notes"><ul>{d.notes.map((n) => <li key={n}>{n}</li>)}</ul></Card>
        </>
      )} />
    </Page>
  )
}

/* ----------------------------------------------------- Drift timeline --- */
export function DriftTimelinePage() {
  return (
    <Page title="Drift timeline">
      <p className="muted">Environment changes over time with root-cause hints (<code>devrepro drift</code>).</p>
      <AsyncDemo fn={loadDriftTimeline} render={(points) => (
        points.length === 0 ? <EmptyState what="snapshot history" /> : (
          <ol className="timeline">
            {points.map((p) => (
              <li key={p.snapshot_id}>
                <div><code>{p.snapshot_id}</code> — <time dateTime={p.created_at}>{new Date(p.created_at).toLocaleString()}</time></div>
                <ul>
                  {p.changed.map((c) => (
                    <li key={c.component}>
                      <strong>{c.component}</strong>: {c.from ?? '(none)'} → {c.to ?? '(removed)'}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )
      )} />
    </Page>
  )
}

/* --------------------------------------------- Generated env preview ---- */
export function GeneratedEnvPage() {
  return (
    <Page title="Generated environment preview">
      <p className="muted">Drafts from <code>devrepro generate</code>. Nothing is written without your review; generated files never overwrite existing ones silently.</p>
      <AsyncDemo fn={loadGeneratedEnv} render={(files) => (
        <>
          {files.map((f) => (
            <Card key={f.target} title={f.target}>
              {f.review_required && <p className="badge badge-warn">REVIEW REQUIRED before committing</p>}
              <pre tabIndex={0}><code>{f.content}</code></pre>
              <CopyBlock text={f.content} />
            </Card>
          ))}
        </>
      )} />
    </Page>
  )
}

/* ---------------------------------------------------- Plugin catalog ---- */
export function PluginCatalogPage() {
  return (
    <Page title="Plugin catalog">
      <p className="muted">Installed extensions per entry-point group with declared capabilities. Plugins performing network or privileged probes must declare it; the UI warns before enabling them.</p>
      <AsyncDemo fn={loadPlugins} render={(plugins) => (
        plugins.length === 0 ? <EmptyState what="installed plugins" /> : (
          <table className="table">
            <thead><tr><th>Name</th><th>Group</th><th>Version</th><th>Capabilities</th><th>Network</th><th>Privileged</th></tr></thead>
            <tbody>{plugins.map((p) => (
              <tr key={p.name}>
                <td>{p.name}</td><td>{p.group}</td><td><code>{p.version}</code></td>
                <td>{p.capabilities.join(', ') || '—'}</td>
                <td>{p.network ? '⚠ yes' : 'no'}</td>
                <td>{p.privileged ? '⚠ yes' : 'no'}</td>
              </tr>
            ))}</tbody>
          </table>
        )
      )} />
    </Page>
  )
}
