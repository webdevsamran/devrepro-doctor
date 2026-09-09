import { useEffect, useRef, useState } from 'react'

/**
 * Charts, hand-drawn in SVG.
 *
 * A charting library would be the larger part of this bundle and would still
 * need overriding to read theme tokens. These read `currentColor` and CSS
 * variables directly, so they follow light/dark and the severity ramp without
 * being told, and they animate through CSS transitions that
 * `prefers-reduced-motion` already disables globally.
 *
 * Every chart is `role="img"` with a text label: a screen reader gets the
 * number, not a description of a shape.
 */

/** Count from 0 to `value` once on mount. Static under reduced motion. */
function useCountUp(value: number, duration = 700): number {
  const [shown, setShown] = useState(0)
  const raf = useRef(0)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      setShown(value)
      return
    }
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      // Ease-out cubic: fast first, settling gently on the real number.
      setShown(value * (1 - Math.pow(1 - t, 3)))
      if (t < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [value, duration])

  return shown
}

export function ScoreRadial({
  value,
  max,
  label,
  size = 132,
}: {
  value: number
  max: number
  label: string
  size?: number
}) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0
  const animated = useCountUp(pct)
  const stroke = 10
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const tone = pct >= 0.75 ? 'var(--sev-pass)' : pct >= 0.4 ? 'var(--sev-warn)' : 'var(--sev-error)'

  return (
    <div className="stack" style={{ alignItems: 'center', gap: 'var(--sp-2)' }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`${label}: ${value} out of ${max}`}
        className="chart"
        style={{ width: size, height: size }}
      >
        <circle
          className="chart-track"
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
        />
        <circle
          className="chart-arc"
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          stroke={tone}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - animated)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text
          className="chart-value"
          x="50%"
          y="47%"
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: size * 0.24 }}
        >
          {value}
        </text>
        <text
          className="chart-label"
          x="50%"
          y="65%"
          textAnchor="middle"
          dominantBaseline="middle"
        >
          of {max}
        </text>
      </svg>
      <span className="stat-label">{label}</span>
    </div>
  )
}

export type Segment = { key: string; value: number; color: string; label: string }

/**
 * A single stacked bar. Used for severity distribution, where the whole is
 * meaningful and the parts are few — a pie would be worse at both.
 */
export function StackedBar({ segments, height = 10 }: { segments: Segment[]; height?: number }) {
  const total = segments.reduce((s, x) => s + x.value, 0)
  if (total === 0) return <div className="meter" style={{ height }} aria-hidden="true" />

  const summary = segments
    .filter((s) => s.value > 0)
    .map((s) => `${s.value} ${s.label}`)
    .join(', ')

  return (
    <div
      className="stack"
      style={{ gap: 'var(--sp-2)' }}
      role="img"
      aria-label={`Findings by severity: ${summary}`}
    >
      <div
        style={{
          display: 'flex',
          height,
          borderRadius: 'var(--radius-full)',
          overflow: 'hidden',
          background: 'var(--surface-3)',
        }}
      >
        {segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <div
              key={s.key}
              className="chart-bar"
              title={`${s.label}: ${s.value}`}
              style={{
                width: `${(s.value / total) * 100}%`,
                background: s.color,
                transition: 'width var(--dur-large) var(--ease-out)',
              }}
            />
          ))}
      </div>
      <div className="legend">
        {segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <span className="legend-item" key={s.key}>
              <span className="legend-swatch" style={{ background: s.color }} />
              {s.label}
              <span className="num subtle">{s.value}</span>
            </span>
          ))}
      </div>
    </div>
  )
}

/** A labelled proportion, for lists of ranked things. */
export function MeterRow({
  label,
  value,
  max,
  hint,
  color = 'var(--accent)',
}: {
  label: string
  value: number
  max: number
  hint?: string
  color?: string
}) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="stack" style={{ gap: 'var(--sp-1)' }}>
      <div className="row-between" style={{ gap: 'var(--sp-2)' }}>
        <span className="small truncate">{label}</span>
        <span className="num small muted">{hint ?? value}</span>
      </div>
      <div className="meter" role="img" aria-label={`${label}: ${hint ?? value}`}>
        <div className="meter-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

/**
 * A compact trend line. `values` are plotted in order; the path is drawn on
 * mount so the eye follows the series rather than being handed a finished
 * shape.
 */
export function Sparkline({
  values,
  label,
  height = 44,
}: {
  values: number[]
  label: string
  height?: number
}) {
  const pathRef = useRef<SVGPathElement>(null)

  useEffect(() => {
    const path = pathRef.current
    if (!path) return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const len = path.getTotalLength()
    path.style.transition = 'none'
    path.style.strokeDasharray = String(len)
    path.style.strokeDashoffset = String(len)
    // Force a reflow so the transition starts from the dashed state.
    void path.getBoundingClientRect()
    path.style.transition = 'stroke-dashoffset var(--dur-large) var(--ease-out)'
    path.style.strokeDashoffset = '0'
  }, [values])

  if (values.length < 2) {
    return <p className="tiny subtle mb-0">Not enough history to plot a trend.</p>
  }

  const w = 100
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = height - ((v - min) / span) * (height - 6) - 3
    return `${x.toFixed(2)},${y.toFixed(2)}`
  })

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className="chart"
      style={{ height }}
      role="img"
      aria-label={`${label}: ${values.length} points, from ${values[0]} to ${values[values.length - 1]}`}
    >
      <path
        ref={pathRef}
        d={`M ${points.join(' L ')}`}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
