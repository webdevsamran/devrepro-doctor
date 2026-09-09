/**
 * Environment diff: side-by-side, semantic, and linkable.
 *
 * The previous version was a six-column table keyed by array index, with every
 * row rendered flat in whatever order the engine emitted. That is a data dump,
 * not a diff viewer: the question someone actually arrives with is "what
 * differs that matters to this project", and the answer was buried among rows
 * classified `same`.
 *
 * Three decisions shape this file:
 *
 * 1. **The classification is the structure.** The engine already did the hard
 *    part -- it decided that a version difference is drift, that a PATH order
 *    change is precedence, and that a missing tool the project requires is
 *    project-critical. Grouping by that and ordering the groups by how much
 *    they should worry you is the whole of the design.
 * 2. **View state lives in the URL.** A diff is something you send to someone.
 *    A link that reopens the filtered view beats a screenshot and a paragraph
 *    of explanation.
 * 3. **Nothing is computed here.** The diff arrives already classified from
 *    `devrepro diff`. Re-deriving any of it in TypeScript would create a second
 *    implementation that drifts from the Python one, and the two would
 *    eventually disagree in front of a user.
 */
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { CopyButton, EmptyState } from '../components/ui'
import { StackedBar, type Segment } from '../components/charts'
import type { DiffEntry, EnvironmentDiff } from '../types'

/** Classification order: most alarming first, `same` last. */
export const CLASSIFICATIONS = [
  'project-critical',
  'missing',
  'version-drift',
  'path-precedence',
  'extra',
  'platform-expected',
  'same',
] as const

const LABELS: Record<string, string> = {
  'project-critical': 'Project critical',
  missing: 'Missing on B',
  'version-drift': 'Version drift',
  'path-precedence': 'PATH precedence',
  extra: 'Only on B',
  'platform-expected': 'Expected for the platform',
  same: 'Identical',
}

const BLURBS: Record<string, string> = {
  'project-critical': 'This project declares it and the two machines disagree.',
  missing: 'Present on A, absent on B.',
  'version-drift': 'Both have it; the versions differ.',
  'path-precedence': 'Same tool, different position on PATH — a shadowing difference.',
  extra: 'Present on B, absent on A.',
  'platform-expected':
    'Differs because the operating systems differ. Reported, not a problem to fix.',
  same: 'No difference. Shown only when asked for.',
}

const SWATCH: Record<string, string> = {
  'project-critical': 'var(--sev-blocked)',
  missing: 'var(--sev-error)',
  'version-drift': 'var(--sev-warn)',
  'path-precedence': 'var(--sev-warn)',
  extra: 'var(--sev-info)',
  'platform-expected': 'var(--sev-info)',
  same: 'var(--sev-pass)',
}

/** Default view: everything that is a difference, nothing that is not. */
const DEFAULT_ACTIVE = CLASSIFICATIONS.filter((c) => c !== 'same' && c !== 'platform-expected')

/**
 * A stable key for a row.
 *
 * `component` plus `name` is not unique on its own: the same binary appears
 * once per PATH position in a precedence entry. Index alone misassociates row
 * state when a filter changes the list. Both together survive both.
 */
export function entryKey(entry: DiffEntry, index: number): string {
  return `${entry.component}::${entry.name}::${entry.classification}::${index}`
}

export function diffToMarkdown(entries: DiffEntry[]): string {
  const NL = String.fromCharCode(10)
  const escape = (text: string) => text.replace(/\|/g, '\\|')
  return [
    '| Classification | Component | Name | A | B |',
    '|---|---|---|---|---|',
    ...entries.map(
      (e) =>
        `| ${e.classification}${e.project_critical ? ' ⚠️' : ''} | ${escape(e.component)} | ` +
        `\`${escape(e.name)}\` | ${escape(e.a_value ?? '—')} | ${escape(e.b_value ?? '—')} |`,
    ),
    '',
    '_Produced by `devrepro diff`. Read-only comparison; values are privacy-redacted._',
  ].join(NL)
}

function Row({ entry }: { entry: DiffEntry }) {
  const changed = entry.a_value !== entry.b_value
  return (
    <tr className={entry.project_critical ? 'row-critical' : undefined}>
      <th scope="row" className="diff-name">
        {/* The flex lives on an inner span, not on the cell. `display: flex`
            on a `th` stops it being a table-cell, so the browser wraps it in
            an anonymous cell and the column widths and borders stop lining up
            with the header. */}
        <span className="diff-name-inner">
          <span className="diff-component">{entry.component}</span>
          <code>{entry.name}</code>
          {entry.project_critical && (
            <span className="pill pill-critical" title="Declared by this project">
              critical
            </span>
          )}
        </span>
      </th>
      <td className={changed ? 'diff-side diff-a' : 'diff-side'}>
        <code>{entry.a_value ?? '—'}</code>
      </td>
      <td className={changed ? 'diff-side diff-b' : 'diff-side'}>
        <code>{entry.b_value ?? '—'}</code>
      </td>
      <td className="diff-detail small muted">{entry.detail ?? ''}</td>
    </tr>
  )
}

export function DiffPage() {
  const [diff, setDiff] = useState<EnvironmentDiff | null>(null)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [params, setParams] = useSearchParams()

  const active = useMemo(() => {
    const raw = params.get('kind')
    return new Set<string>(raw ? raw.split(',').filter(Boolean) : DEFAULT_ACTIVE)
  }, [params])
  const query = params.get('q') ?? ''
  const criticalOnly = params.get('critical') === '1'

  const update = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(params)
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  const load = useCallback(async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as EnvironmentDiff
      if (!Array.isArray(parsed.entries)) throw new Error('no entries')
      setDiff(parsed)
      setError('')
    } catch {
      setDiff(null)
      setError(
        `${file.name} is not an environment diff. Produce one with ` +
          '`devrepro diff A.json B.json --format json -o diff.json`.',
      )
    }
  }, [])

  const counts = useMemo(() => {
    const tally: Record<string, number> = {}
    for (const e of diff?.entries ?? []) tally[e.classification] = (tally[e.classification] ?? 0) + 1
    return tally
  }, [diff])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (diff?.entries ?? [])
      .filter((e) => active.has(e.classification))
      .filter((e) => !criticalOnly || e.project_critical)
      .filter(
        (e) =>
          !needle ||
          e.name.toLowerCase().includes(needle) ||
          e.component.toLowerCase().includes(needle),
      )
  }, [diff, active, criticalOnly, query])

  const grouped = useMemo(() => {
    const buckets = new Map<string, DiffEntry[]>()
    for (const e of visible) {
      const bucket = buckets.get(e.classification)
      // Project-critical rows lead their group: they are the reason someone
      // opened the file.
      if (bucket) bucket.push(e)
      else buckets.set(e.classification, [e])
    }
    for (const rows of buckets.values()) {
      rows.sort(
        (a, b) =>
          Number(b.project_critical) - Number(a.project_critical) ||
          a.component.localeCompare(b.component) ||
          a.name.localeCompare(b.name),
      )
    }
    return CLASSIFICATIONS.filter((c) => buckets.has(c)).map(
      (c) => [c, buckets.get(c) as DiffEntry[]] as const,
    )
  }, [visible])

  const segments: Segment[] = CLASSIFICATIONS.filter((c) => counts[c]).map((c) => ({
    key: c,
    value: counts[c],
    color: SWATCH[c],
    label: LABELS[c],
  }))

  return (
    <>
      <div className="row-between">
        <h2 className="mb-0">Environment diff</h2>
        {diff && <CopyButton text={diffToMarkdown(visible)} label="Copy as Markdown" />}
      </div>

      {!diff && (
        <div
          className={dragging ? 'dropzone dropzone-active' : 'dropzone'}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files?.[0]
            if (file) void load(file)
          }}
        >
          <p className="mb-0">
            Drop a diff JSON here, or{' '}
            <label className="link-button">
              choose a file
              <input
                type="file"
                accept=".json,application/json"
                aria-label="Diff JSON file"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) void load(file)
                }}
              />
            </label>
            .
          </p>
          <p className="tiny muted mb-0">
            Produce one with{' '}
            <code>devrepro diff machineA.json machineB.json --format json -o diff.json</code>. The
            file is read in this browser and never uploaded.
          </p>
        </div>
      )}

      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}

      {diff && (
        <>
          <div className="card enter">
            <div className="row-between">
              <p className="small muted mb-0">
                <code>{diff.a_snapshot_id}</code> → <code>{diff.b_snapshot_id}</code> ·{' '}
                {diff.entries.length} entries
              </p>
              <button className="btn-ghost" onClick={() => setDiff(null)}>
                Load a different diff
              </button>
            </div>
            <div className="mt-4">
              <StackedBar segments={segments} />
            </div>
            <div className="row mt-4 wrap">
              {CLASSIFICATIONS.map((c) => (
                <label
                  key={c}
                  className={active.has(c) ? 'chip chip-on' : 'chip'}
                  title={BLURBS[c]}
                >
                  <input
                    type="checkbox"
                    checked={active.has(c)}
                    onChange={() => {
                      const next = new Set(active)
                      if (next.has(c)) next.delete(c)
                      else next.add(c)
                      update('kind', [...next].join(','))
                    }}
                  />
                  <span className="swatch" style={{ background: SWATCH[c] }} aria-hidden="true" />
                  {LABELS[c]}
                  <span className="chip-count">{counts[c] ?? 0}</span>
                </label>
              ))}
            </div>
            <div className="row mt-4">
              <input
                className="input"
                placeholder="Search component or name…"
                aria-label="Search diff entries"
                value={query}
                onChange={(e) => update('q', e.target.value)}
              />
              <label className="row small muted nowrap">
                <input
                  type="checkbox"
                  checked={criticalOnly}
                  onChange={(e) => update('critical', e.target.checked ? '1' : null)}
                />
                Project-critical only
              </label>
            </div>
            <p className="tiny muted mt-4 mb-0">
              Showing {visible.length} of {diff.entries.length}. Filters are in the URL, so this
              view can be linked to.
            </p>
          </div>

          {grouped.length === 0 ? (
            <EmptyState
              what="matching entries"
              hint="Every classification may be filtered out — check the chips above."
            />
          ) : (
            grouped.map(([kind, rows]) => (
              <section key={kind} className="enter">
                <h3 className="mt-4 row">
                  <span className="swatch" style={{ background: SWATCH[kind] }} aria-hidden="true" />
                  {LABELS[kind]} <span className="subtle small">({rows.length})</span>
                </h3>
                <p className="small muted mt-0">{BLURBS[kind]}</p>
                <div className="table-scroll">
                  <table className="table table-diff">
                    <thead>
                      <tr>
                        <th scope="col">Component</th>
                        <th scope="col">A</th>
                        <th scope="col">B</th>
                        {/* Same class as its cells: hiding the column on a
                            narrow screen has to take the header with it, or
                            the row backgrounds and borders stop one column
                            short of the header. */}
                        <th scope="col" className="diff-detail">
                          Detail
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((entry, index) => (
                        <Row key={entryKey(entry, index)} entry={entry} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))
          )}
        </>
      )}
    </>
  )
}
