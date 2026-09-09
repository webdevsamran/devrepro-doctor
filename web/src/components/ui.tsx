import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Finding, FindingState } from '../types'

export function Badge({ state }: { state: FindingState | string }) {
  return <span className={`badge badge-${state.toLowerCase()}`}>{state}</span>
}

export function Card({
  title,
  hint,
  actions,
  children,
  className,
}: {
  title?: string
  hint?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className ?? ''}`}>
      {(title || actions) && (
        <header className="card-header">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {hint && <p className="card-hint">{hint}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  sub,
}: {
  label: string
  value: ReactNode
  sub?: string
}) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

export function Loading({ what = 'sanitized scan data' }: { what?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>Loading {what}…</p>
    </div>
  )
}

/**
 * Placeholder for a lazily loaded route.
 *
 * Shaped like the page that is arriving — a header and a few cards — so the
 * layout does not jump when the real content lands. A spinner in the same
 * position would communicate less and shift more.
 */
export function RouteSkeleton() {
  return (
    <div className="stack" aria-busy="true" aria-live="polite">
      <span className="visually-hidden">Loading view…</span>
      <div className="skeleton" style={{ height: '1.5rem', width: '14rem' }} />
      <div className="grid grid-2">
        {[0, 1, 2, 3].map((i) => (
          <div className="card" key={i}>
            <div className="skeleton skeleton-line" style={{ width: '40%' }} />
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state state-error" role="alert">
      <div className="state-icon" aria-hidden="true">
        ⚠
      </div>
      <h2>Could not load report</h2>
      <p className="muted">{message}</p>
      <p className="small muted">
        Run <code>devrepro serve</code> and open this page from the local server, or place a
        sanitized <code>report.json</code> (<code>devrepro scan -o report.json</code>) beside
        the app.
      </p>
    </div>
  )
}

export function EmptyState({ what, hint }: { what: string; hint?: string }) {
  return (
    <div className="state">
      <div className="state-icon" aria-hidden="true">
        ○
      </div>
      <p>No {what} in this report.</p>
      {hint && <p className="small subtle">{hint}</p>}
    </div>
  )
}

/**
 * Fixture data must never be mistaken for a reading of the machine.
 *
 * This is a diagnostics tool: a plausible-looking green score that came from a
 * fixture is worse than an empty page, because the empty page cannot mislead.
 */
export function DemoBanner({ what }: { what: string }) {
  return (
    <p className="demo-banner" role="status">
      <span aria-hidden="true">◑</span>
      DEMO DATA — {what} is not available from this machine. Nothing here reflects your
      environment.
    </p>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])

  return (
    <>
      <button
        className="btn btn-sm"
        onClick={() => {
          navigator.clipboard?.writeText(text).then(
            () => setCopied(true),
            () => setCopied(false),
          )
        }}
        aria-label={`Copy ${label}`}
      >
        <span aria-hidden="true">{copied ? '✓' : '⧉'}</span>
        {copied ? 'Copied' : label}
      </button>
      {/* Announced once, then removed, so a screen reader hears the result of
          an action that is otherwise purely visual. */}
      {copied && (
        <span role="status" aria-live="polite" className="visually-hidden">
          {label} copied to clipboard
        </span>
      )}
    </>
  )
}

const SEVERITIES: FindingState[] = ['BLOCKED', 'ERROR', 'WARN', 'UNKNOWN', 'INFO', 'PASS']

export function SeverityFilter({
  selected,
  counts,
  onToggle,
}: {
  selected: Set<string>
  counts?: Record<string, number>
  onToggle: (s: FindingState) => void
}) {
  return (
    <div className="row" role="group" aria-label="Filter by severity">
      {SEVERITIES.map((s) => (
        <label key={s} className={selected.has(s) ? 'chip chip-on' : 'chip'}>
          <input type="checkbox" checked={selected.has(s)} onChange={() => onToggle(s)} />
          {s}
          {counts && <span className="chip-count">{counts[s] ?? 0}</span>}
        </label>
      ))}
    </div>
  )
}

export function EvidenceDrawer({ finding }: { finding: Finding }) {
  return (
    <details className="evidence-drawer">
      <summary>Evidence &amp; remediation</summary>
      {finding.remediation_hint && (
        <p className="remediation-hint">
          <strong>Safe remediation:</strong> {finding.remediation_hint}
        </p>
      )}
      {finding.evidence.map((ev, i) => (
        <pre key={i}>
          {ev.command ? ev.command.join(' ') : ev.path || ev.source}
          {ev.excerpt ? String.fromCharCode(10) + ev.excerpt : ''}
        </pre>
      ))}
      {finding.references && finding.references.length > 0 && (
        <p className="refs">Refs: {finding.references.join(', ')}</p>
      )}
    </details>
  )
}
