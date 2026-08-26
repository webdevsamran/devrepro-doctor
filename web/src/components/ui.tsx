import type { ReactNode } from 'react'
import type { Finding, FindingState } from '../types'

export function Badge({ state }: { state: FindingState | string }) {
  return <span className={`badge badge-${state.toLowerCase()}`}>{state}</span>
}

export function Card({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ''}`}>
      {title && <h3>{title}</h3>}
      {children}
    </section>
  )
}

export function Loading() {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>Loading sanitized scan data…</p>
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state state-error" role="alert">
      <h2>Could not load report</h2>
      <p>{message}</p>
      <p>
        Run <code>devrepro serve</code> and open this page via the local server,
        or place a sanitized <code>report.json</code> (<code>devrepro scan -o report.json</code>)
        next to the app.
      </p>
    </div>
  )
}

export function EmptyState({ what }: { what: string }) {
  return (
    <div className="state">
      <p>No {what} found in this report.</p>
    </div>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  return (
    <button
      className="btn btn-small"
      onClick={() => navigator.clipboard.writeText(text)}
      aria-label={`Copy ${label}`}
    >
      ⧉ {label}
    </button>
  )
}

const SEVERITIES: FindingState[] = ['BLOCKED', 'ERROR', 'WARN', 'UNKNOWN', 'INFO', 'PASS']

export function SeverityFilter({
  selected,
  onToggle,
}: {
  selected: Set<string>
  onToggle: (s: FindingState) => void
}) {
  return (
    <div className="severity-filter" role="group" aria-label="Filter by severity">
      {SEVERITIES.map((s) => (
        <label key={s} className={selected.has(s) ? 'chip chip-on' : 'chip'}>
          <input
            type="checkbox"
            checked={selected.has(s)}
            onChange={() => onToggle(s)}
          />
          {s}
        </label>
      ))}
    </div>
  )
}

export function EvidenceDrawer({ finding }: { finding: Finding }) {
  return (
    <details className="evidence-drawer">
      <summary>Evidence & remediation</summary>
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