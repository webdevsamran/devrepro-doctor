import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { t } from '../i18n'
import type { Finding, FindingState } from '../types'

export function Badge({ state }: { state: FindingState | string }) {
  return <span className={`badge badge-${state.toLowerCase()}`}>{state}</span>
}

/**
 * True while an element can actually be scrolled sideways.
 *
 * A `.card` scrolls horizontally when its content overflows, and a scrollable
 * region that cannot be focused is unreachable for anyone not using a mouse --
 * axe reports it as a serious violation, correctly. Adding `tabIndex` to every
 * card would fix that by putting thirty-odd empty stops in the tab order, so
 * the attribute follows the measurement instead: only a card that really has
 * somewhere to scroll becomes a stop.
 */
function useHorizontallyScrollable() {
  const ref = useRef<HTMLElement | null>(null)
  const [scrollable, setScrollable] = useState(false)

  const measure = useCallback(() => {
    const el = ref.current
    if (el) setScrollable(el.scrollWidth > el.clientWidth + 1)
  }, [])

  useEffect(() => {
    measure()
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    // Content and viewport both change: a filter can shorten a table, and a
    // rotation can widen the card.
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    for (const child of Array.from(el.children)) observer.observe(child)
    return () => observer.disconnect()
  }, [measure])

  return { ref, scrollable }
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
  const { ref, scrollable } = useHorizontallyScrollable()
  return (
    <section
      ref={ref}
      className={`card ${className ?? ''}`}
      {...(scrollable
        ? { tabIndex: 0, role: 'region', 'aria-label': title ? `${title}, scrollable` : 'Scrollable content' }
        : {})}
    >
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

export function Loading({ what = t('state.loadingDefault') }: { what?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>{t('state.loading', { what })}</p>
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
      <span className="visually-hidden">{t('state.loadingView')}</span>
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
      <h2>{t('state.errorTitle')}</h2>
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
      <p>{t('state.empty', { what })}</p>
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
      {t('state.demo', { what })}
    </p>
  )
}

/**
 * Async data with a demo fallback that can never be mistaken for a reading.
 *
 * This lived in `pages/platform.tsx` alongside a second `DemoBanner` of its
 * own -- so a page imported a shared component from another page, and the two
 * banners said different things, only one of which went through the catalogue.
 *
 * `what` is required rather than optional. The plan's rule for this console is
 * that a fixture must never look like real data, and a banner that names the
 * dataset it stood in for is a stronger claim than a generic one: "DEMO DATA --
 * the audit log is not available from this machine" cannot be skimmed past the
 * way a bare "DEMO DATA" can.
 */
export function AsyncDemo<T>({
  what,
  fn,
  render,
}: {
  what: string
  // `data` is nullable here because `WithDemo` declares it so. The previous
  // version took `T` and called `render(result.data as T)`, and that cast is
  // the whole reason this is worth writing down: a null payload went straight
  // into `events.map(...)` and took the route down with a TypeError. Typed
  // honestly, the compiler demands the empty state that was always missing.
  fn: () => Promise<{ data: T | null; demo: boolean; error: string }>
  // `NonNullable<T>`, so the absence of data is this component's problem and
  // never the caller's. Every `render` here indexes or maps over what it is
  // given; none of them should have to ask whether it exists.
  render: (data: NonNullable<T>) => ReactNode
}) {
  const [state, setState] = useState<{ data: NonNullable<T>; demo: boolean } | null>(null)
  const [empty, setEmpty] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    fn().then(
      (result) => {
        if (!live) return
        if (result.data === null || result.data === undefined) setEmpty(true)
        else setState({ data: result.data, demo: result.demo })
      },
      (err: unknown) => live && setError(err instanceof Error ? err.message : String(err)),
    )
    return () => {
      live = false
    }
  }, [fn])

  if (error) return <ErrorState message={error} />
  if (empty) return <EmptyState what={what} />
  if (!state) return <Loading what={what} />
  return (
    <>
      {state.demo && <DemoBanner what={what} />}
      {render(state.data)}
    </>
  )
}

export function CopyButton({
  text,
  label = t('action.copy'),
}: {
  text: string
  label?: string
}) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])

  return (
    <>
      {/* No `aria-label`. It used to be `Copy ${label}`, which made the default
          name "Copy Copy" and the others "Copy Copy as Markdown" -- a stutter
          nobody sees and every screen reader says. The button's own text is
          already the right name.

          The glyph moved to CSS for the same reason as the palette button's:
          `aria-hidden` hides it from assistive technology and not from the
          person looking at the screen, so it still counted as visible label
          text under WCAG 2.2 SC 2.5.3 and no accessible name could contain it
          without becoming unspeakable. */}
      <button
        className="btn btn-sm btn-copy"
        data-copied={copied}
        onClick={() => {
          navigator.clipboard?.writeText(text).then(
            () => setCopied(true),
            () => setCopied(false),
          )
        }}
      >
        {copied ? t('action.copied') : label}
      </button>
      {/* Announced once, then removed, so a screen reader hears the result of
          an action that is otherwise purely visual. */}
      {copied && (
        <span role="status" aria-live="polite" className="visually-hidden">
          {t('action.copyAnnounce', { label })}
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
    <div className="row" role="group" aria-label={t('action.filterSeverity')}>
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
