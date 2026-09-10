import { useMemo, useState } from 'react'

import { ExportBar, reportToMarkdown } from '../components/export'
import { Badge, Card, EmptyState } from '../components/ui'
import { ScoreRadial, StackedBar, VersionHeatmap } from '../components/charts'
import type { ScanReport } from '../types'

/**
 * Three views that are about the console itself rather than about a machine:
 * a snapshot viewer, a component gallery, and a tour.
 */

/* ------------------------------------------------------------------ viewer */

/**
 * Paste a snapshot, read the report. Nothing is uploaded.
 *
 * The situation this is for: somebody's build fails, a colleague asks for
 * `devrepro snapshot`, and now there is a 200 KB JSON file in a chat thread
 * that nobody can read. Every tool that solves this solves it with an upload —
 * and a snapshot describes a developer's machine, so an upload is the one thing
 * this project will not add.
 *
 * `FileReader` and `JSON.parse`, in the page. The file never leaves the
 * browser, there is no endpoint behind this, and the page says so where
 * somebody about to paste a colleague's machine state will read it.
 */
export function SnapshotViewerPage() {
  const [raw, setRaw] = useState('')
  const [error, setError] = useState<string | null>(null)

  const parsed = useMemo<ScanReport | null>(() => {
    if (!raw.trim()) return null
    try {
      const value = JSON.parse(raw) as unknown
      if (!value || typeof value !== 'object') throw new Error('not an object')
      const report = value as ScanReport
      if (!report.platform && !report.findings && !report.tools) {
        throw new Error('no platform, findings or tools — is this a devrepro snapshot?')
      }
      return report
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'could not parse')
      return null
    }
  }, [raw])

  function load(text: string) {
    setError(null)
    setRaw(text)
  }

  function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => load(String(reader.result ?? ''))
    reader.onerror = () => setError('The file could not be read.')
    reader.readAsText(file)
  }

  const findings = parsed?.findings ?? []
  const counts = findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.state] = (acc[f.state] ?? 0) + 1
    return acc
  }, {})

  return (
    <section>
      <h1>Snapshot viewer</h1>
      <p>
        Paste or open a <code>devrepro snapshot</code> file to read it. <strong>Nothing is
        uploaded</strong> — the file is parsed in this browser tab, there is no endpoint behind this
        page, and closing the tab is the whole of the cleanup.
      </p>

      <Card title="Load a snapshot">
        <input type="file" accept="application/json,.json" onChange={onFile} aria-label="Snapshot file" />
        <textarea
          className="snapshot-input"
          rows={6}
          value={raw}
          spellCheck={false}
          placeholder="…or paste the JSON here"
          aria-label="Snapshot JSON"
          onChange={(e) => load(e.target.value)}
        />
        {error && raw.trim() && (
          <p className="state-error" role="alert">
            Could not read that: {error}
          </p>
        )}
      </Card>

      {!parsed && !raw.trim() && (
        <EmptyState
          what="No snapshot loaded"
          hint="Run `devrepro snapshot -o machine.json` and open the file here."
        />
      )}

      {parsed && (
        <>
          <ExportBar report={parsed} />
          <div className="grid grid-2">
            <Card title="Machine">
              <dl className="kv">
                <dt>OS</dt>
                <dd>
                  {parsed.platform?.os_name} {parsed.platform?.os_version}
                </dd>
                <dt>Architecture</dt>
                <dd>{parsed.platform?.arch}</dd>
                <dt>Scanned</dt>
                <dd>{parsed.created_at ?? 'unknown'}</dd>
                <dt>devrepro</dt>
                <dd>{parsed.devrepro_version ?? 'unknown'}</dd>
              </dl>
            </Card>
            <Card title="Findings">
              <StackedBar
                segments={Object.entries(counts).map(([state, n]) => ({
                  key: state,
                  label: state,
                  value: n,
                  // The severity ramp is a token, so the bar follows the theme
                  // without a second palette to keep in step.
                  color: `var(--sev-${state.toLowerCase()})`,
                }))}
              />
              <p className="muted">{findings.length} finding(s)</p>
            </Card>
          </div>

          {findings.length > 0 && (
            <Card title="What it found">
              <table className="table">
                <thead>
                  <tr>
                    <th>State</th>
                    <th>Rule</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.slice(0, 200).map((finding, index) => (
                    <tr key={`${finding.rule_id}-${index}`}>
                      <td>
                        <Badge state={finding.state} />
                      </td>
                      <td>
                        <code>{finding.rule_id}</code>
                      </td>
                      <td>{finding.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </section>
  )
}

/* ----------------------------------------------------------------- gallery */

/**
 * Every component, rendered in every state it has, in the real application.
 *
 * This is the Storybook-shaped need without Storybook. Storybook is ~40 MB of
 * devDependencies, its own build, its own config and a second place for the
 * theme tokens to be defined — for a design system of about a dozen
 * components.
 *
 * A route inside the app is better here for a reason that is not only size: a
 * component rendered in the real shell inherits the real tokens, the real
 * theme toggle and the real reduced-motion setting, so a story that looks right
 * here *is* right. A Storybook story renders in an iframe with its own
 * decorators, which is exactly where token drift hides.
 *
 * Visual regression rides on the existing Playwright suite: it screenshots this
 * one route in both themes, which is a stable target precisely because it is
 * every component at once.
 */
export function GalleryPage() {
  const states = ['BLOCKED', 'ERROR', 'WARN', 'INFO', 'PASS', 'UNKNOWN'] as const
  return (
    <section>
      <h1>Component gallery</h1>
      <p>
        Every component in every state, rendered in the real shell — so it inherits the real tokens,
        the real theme and the real motion settings. A story that looks right here is right.
      </p>

      <Card title="Severity badges">
        <div className="gallery-row">
          {states.map((state) => (
            <Badge key={state} state={state} />
          ))}
        </div>
        <p className="muted">
          Never colour alone: each carries its own label, because a severity a reader cannot
          distinguish is a severity that is not communicated.
        </p>
      </Card>

      <Card title="Score radial">
        <div className="gallery-row">
          <ScoreRadial value={9} max={9} label="ready" />
          <ScoreRadial value={5} max={9} label="partial" />
          <ScoreRadial value={0} max={9} label="none" />
        </div>
      </Card>

      <Card title="Stacked bar">
        <StackedBar
          segments={[
            { key: 'blocked', label: 'BLOCKED', value: 1, color: 'var(--sev-blocked)' },
            { key: 'warn', label: 'WARN', value: 6, color: 'var(--sev-warn)' },
            { key: 'pass', label: 'PASS', value: 20, color: 'var(--sev-pass)' },
          ]}
        />
      </Card>

      <Card title="Version heatmap">
        <VersionHeatmap
          heatmap={{
            python: { '3.12.1': 8, '3.11.9': 3, '3.9.6': 1 },
            node: { '22.11.0': 12 },
          }}
        />
      </Card>

      <Card title="Empty state">
        <EmptyState what="Nothing here yet" hint="Run `devrepro doctor` to populate it." />
      </Card>
    </section>
  )
}

/* -------------------------------------------------------------------- tour */

const TOUR_STEPS: { title: string; body: string; where: string }[] = [
  {
    title: 'Start with the verdict',
    body:
      'Machine Overview answers one question: can this machine build this project right now. ' +
      'Everything else in this console exists to explain that answer.',
    where: 'Overview → Machine Overview',
  },
  {
    title: 'A finding is a rule id, and the id is the stable part',
    body:
      'Summaries get reworded; rule ids do not. Quoting one in an issue is the thing that still ' +
      'means something in six months, and `devrepro explain <id>` is the long form.',
    where: 'Diagnose → Findings',
  },
  {
    title: 'PATH order is why the wrong tool wins',
    body:
      'The commonest "installed but not found" is a version manager whose shims sit after the real ' +
      'installation. The explorer draws which candidate wins and why.',
    where: 'Environment → PATH Explorer',
  },
  {
    title: 'Two snapshots explain "works on my machine"',
    body:
      'One snapshot describes a machine. Two, diffed, describe a disagreement — and the diff is ' +
      'grouped so the project-critical differences are not buried under forty harmless ones.',
    where: 'Reproduce → Environment Diff',
  },
  {
    title: 'Nothing here leaves your machine',
    body:
      'This console reads a sanitized report. There is no account, no endpoint and no telemetry, ' +
      'and the snapshot viewer parses a colleague’s file in your own browser tab.',
    where: 'About → Privacy',
  },
]

/**
 * A tour that is a page rather than a modal that ambushes you.
 *
 * Product tours are overwhelmingly disliked, and the reason is consistent: they
 * interrupt somebody who came to do something specific, on their first visit,
 * when they have the least patience for it. So this one never launches itself.
 * It sits in the navigation, it can be read start to finish in a minute, and
 * every step names where the thing it describes actually is — which is the part
 * a modal sequence takes away by moving you there itself.
 */
export function TourPage() {
  return (
    <section>
      <h1>A short tour</h1>
      <p>
        Five things worth knowing. This never opens itself — a tour that ambushes somebody on their
        first visit interrupts the thing they came to do, which is why nobody finishes one.
      </p>
      <ol className="tour">
        {TOUR_STEPS.map((step) => (
          <li key={step.title} className="tour-step">
            <h2>{step.title}</h2>
            <p>{step.body}</p>
            <p className="muted">Where: {step.where}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

export { reportToMarkdown }
