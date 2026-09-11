/**
 * Wave-11 pages: shell startup, containers/WSL, GPU/AI stack, drift timeline,
 * generated environment preview and the plugin catalog. Enterprise console
 * pages live in pages4.tsx. Demo fallbacks always show a visible DEMO banner.
 */
import {
  loadDriftTimeline, loadGeneratedEnv, loadGpuAi,
  loadPlugins, loadShellStartup, useAsync2, type WithDemo,
} from '../api/console'
import { Badge, Card, CopyButton, EmptyState } from '../components/ui'
import type { ScanReport } from '../types'

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
/** Human-readable bytes, in the decimal units docker itself prints. */
function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const units = ['B', 'kB', 'MB', 'GB', 'TB']
  let n = value
  let i = 0
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000
    i += 1
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/** The engine's own name for itself, expanded into something readable. */
const BACKEND_LABELS: Record<string, string> = {
  'docker-desktop': 'Docker Desktop',
  colima: 'Colima',
  'rancher-desktop': 'Rancher Desktop',
  orbstack: 'OrbStack',
  podman: 'Podman',
  lima: 'Lima',
  minikube: 'minikube',
  native: 'native daemon',
}

function Row({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="kv-row">
      {/* The hint sits under the value, not beside the label: wedged into the
          label column it pushed the value into a strip too narrow to hold a
          version string without breaking it across three lines. */}
      <dt className="kv-key">{label}</dt>
      <dd className="kv-value">
        <span>{value}</span>
        {hint && <span className="kv-hint">{hint}</span>}
      </dd>
    </div>
  )
}

/**
 * Containers & WSL, from the scan report.
 *
 * This view ran on a demo fixture unconditionally: it fetched
 * `/api/containers-wsl`, an endpoint the server does not implement, and fell
 * back to invented values on every load. A diagnostics tool showing a
 * plausible green container panel that describes nobody's machine is worse
 * than showing nothing, so it now reads the report the console already has.
 *
 * The interesting fields are new. Daemon health was all a report carried, and
 * "is the daemon up" is the one container question that answers itself the
 * moment you try to use it. Which *engine* is answering, whether it is
 * emulating another architecture, and how much of the disk is reclaimable are
 * the ones that cost an afternoon.
 */
export function ContainersWslPage({ report }: { report: ScanReport }) {
  const c = report.containers
  const wsl = report.wsl
  const emulated =
    c?.server_arch && report.platform.arch
      ? normaliseArch(c.server_arch) !== normaliseArch(report.platform.arch)
      : false

  return (
    <Page title="Containers & WSL">
      {!c ? (
        <EmptyState
          what="container state"
          hint="This report predates container capture. Re-run `devrepro scan`."
        />
      ) : (
        <div className="grid grid-pair">
          <Card
            title="Container engine"
            hint={
              c.backend
                ? (BACKEND_LABELS[c.backend] ?? c.backend)
                : 'engine not identified'
            }
          >
            <dl className="kv">
              <Row
                label="Daemon"
                value={
                  c.docker_daemon_ok ? (
                    <Badge state="PASS" />
                  ) : (
                    <Badge state={c.docker_cli_version ? 'BLOCKED' : 'INFO'} />
                  )
                }
              />
              <Row label="CLI" value={<code>{c.docker_cli_version ?? '—'}</code>} />
              <Row label="Server" value={<code>{c.server_version ?? '—'}</code>} />
              <Row
                label="Context"
                value={
                  <>
                    <code>{c.context_name ?? '—'}</code>
                    {c.endpoint_kind && <span className="tiny subtle"> via {c.endpoint_kind}</span>}
                  </>
                }
                hint="socket path is never collected"
              />
              <Row label="Compose" value={<code>{c.compose_version ?? '—'}</code>} />
              <Row label="buildx" value={<code>{c.buildx_version ?? 'unavailable'}</code>} />
            </dl>
          </Card>

          <Card title="Engine configuration">
            <dl className="kv">
              <Row
                label="Architecture"
                value={
                  <>
                    <code>{c.server_arch ?? '—'}</code>
                    {emulated && (
                      <span className="pill pill-critical" title="Builds run under emulation">
                        emulated
                      </span>
                    )}
                  </>
                }
              />
              <Row
                label="cgroups"
                value={
                  <>
                    <code>{c.cgroup_version ? `v${c.cgroup_version}` : '—'}</code>
                    {c.cgroup_driver && <span className="tiny subtle"> {c.cgroup_driver}</span>}
                  </>
                }
              />
              <Row label="Storage driver" value={<code>{c.storage_driver ?? '—'}</code>} />
              <Row label="Rootless" value={c.rootless === null || c.rootless === undefined ? '—' : String(c.rootless)} />
              <Row
                label="Engine resources"
                value={
                  c.engine_cpus || c.engine_memory_bytes
                    ? `${c.engine_cpus ?? '?'} CPU · ${bytes(c.engine_memory_bytes)}`
                    : '—'
                }
                hint="what the VM was given, not the host"
              />
            </dl>
          </Card>

          <Card title="Disk" hint="reported by the daemon; nothing is pruned">
            <dl className="kv">
              <Row label="Reclaimable" value={bytes(c.reclaimable_bytes)} />
              <Row label="Dangling images" value={c.dangling_images ?? '—'} />
              <Row label="Unused volumes" value={c.unused_volumes ?? '—'} />
            </dl>
            {c.reclaimable_bytes ? (
              <p className="tiny muted mb-0">
                <code>docker system prune -a --volumes</code> reclaims it. This console never
                runs it — pruning deletes data.
              </p>
            ) : null}
          </Card>

          <Card title="Other engines & WSL">
            {c.other_runtimes && c.other_runtimes.length > 0 ? (
              <>
                <p className="small mb-0">Also installed:</p>
                <ul>
                  {c.other_runtimes.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
                {c.other_runtimes.length > 1 && (
                  <p className="tiny muted">
                    More than one engine makes <code>docker context</code> load-bearing: a
                    context pointing at a stopped VM fails exactly like no daemon at all.
                  </p>
                )}
              </>
            ) : (
              <p className="small muted">No alternative container engine on PATH.</p>
            )}

            <h4 className="mt-4">WSL</h4>
            {wsl?.available ? (
              <dl className="kv">
                <Row label="Version" value={<code>{wsl.version ?? '—'}</code>} />
                <Row label="Default" value={<code>{wsl.default_distro ?? '—'}</code>} />
                <Row label="Distros" value={(wsl.distros ?? []).join(', ') || '—'} />
                <Row
                  label="Interop"
                  value={
                    wsl.interop_enabled === null || wsl.interop_enabled === undefined
                      ? '—'
                      : String(wsl.interop_enabled)
                  }
                />
              </dl>
            ) : (
              <p className="small muted">WSL is not available on this machine.</p>
            )}
          </Card>
        </div>
      )}

      <Card title="Findings">
        {report.findings.filter((f) => f.rule_id.startsWith('containers/')).length === 0 ? (
          <p className="small muted mb-0">No container findings in this report.</p>
        ) : (
          <ul className="reset">
            {report.findings
              .filter((f) => f.rule_id.startsWith('containers/'))
              .map((f, i) => (
                <li key={`${f.rule_id}::${i}`} className="row mb-0">
                  <Badge state={f.state} />
                  <code>{f.rule_id}</code>
                  <span className="small">{f.summary}</span>
                </li>
              ))}
          </ul>
        )}
      </Card>
    </Page>
  )
}

const ARCH_ALIASES: Record<string, string> = {
  amd64: 'x86_64',
  x86_64: 'x86_64',
  x64: 'x86_64',
  arm64: 'aarch64',
  aarch64: 'aarch64',
}

/** Python reports `AMD64`, docker reports `x86_64`; compare them normalised. */
function normaliseArch(arch: string): string {
  return ARCH_ALIASES[arch.toLowerCase()] ?? arch.toLowerCase()
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
              <CopyButton text={f.content} />
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
