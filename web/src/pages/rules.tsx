/**
 * The rule catalogue: every id the tool can emit, searchable.
 *
 * This page listed the rule *packs* that happened to appear in the current
 * report -- six or seven cards with a count on each. That answers "what did
 * this scan touch", which the Findings page already answers better, and it
 * cannot answer the question someone actually arrives with: what does
 * `containers/cgroup-v1` mean and what do I do about it.
 *
 * The catalogue is generated from `devrepro/rules/catalog.py` by
 * `scripts/generate_rule_docs.py`, which also writes `docs/RULES.md` and has a
 * `--check` mode in CI. One source, two renderings, and a gate that fails when
 * either drifts -- the alternative is a second catalogue that slowly stops
 * being true.
 *
 * Findings from the current report are cross-referenced where they exist, so
 * "this rule fired here" and "this rule exists" stay visibly different claims.
 */
import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import catalogue from '../data/rules.json' with { type: 'json' }
import { Badge, CopyButton, EmptyState } from '../components/ui'
import type { ScanReport } from '../types'

type RuleDoc = {
  rule_id: string
  prefix: string
  suffix: string
  title: string
  means: string
  matters: string
  fix: string
  /** The prefix is a runtime value, so the entry is representative. */
  composed: boolean
}

const RULES = catalogue.rules as RuleDoc[]

/** Every pack that has at least one documented rule, alphabetically. */
const PREFIXES = [...new Set(RULES.map((r) => r.prefix))].sort()

function matches(rule: RuleDoc, needle: string): boolean {
  if (!needle) return true
  const haystack = `${rule.rule_id} ${rule.title} ${rule.means} ${rule.matters} ${rule.fix}`
  return haystack.toLowerCase().includes(needle)
}

export function RulesPage({ report }: { report?: ScanReport }) {
  const [params, setParams] = useSearchParams()
  const query = params.get('q') ?? ''
  const prefix = params.get('pack') ?? ''
  const selected = params.get('rule') ?? ''

  const update = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }

  /** Rule ids the current report actually emitted, and how often.
   *
   *  Optional on purpose: the catalogue is documentation and renders without a
   *  scan. The cross-reference column is the only part that needs one, and it
   *  says so rather than showing zeroes, because "this rule did not fire" and
   *  "no scan has run" are different facts.
   */
  const observed = useMemo(() => {
    const tally = new Map<string, number>()
    for (const finding of report?.findings ?? []) {
      tally.set(finding.rule_id, (tally.get(finding.rule_id) ?? 0) + 1)
      // A composed id -- `uv/multiple-installations` -- is documented under a
      // representative prefix, so the catalogue entry is keyed by its suffix.
      const suffix = finding.rule_id.split('/').slice(1).join('/')
      if (suffix) tally.set(`*/${suffix}`, (tally.get(`*/${suffix}`) ?? 0) + 1)
    }
    return tally
  }, [report?.findings])

  const seen = (rule: RuleDoc): number =>
    observed.get(rule.rule_id) ?? (rule.composed ? (observed.get(`*/${rule.suffix}`) ?? 0) : 0)

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return RULES.filter((r) => !prefix || r.prefix === prefix).filter((r) => matches(r, needle))
  }, [query, prefix])

  const active = RULES.find((r) => r.rule_id === selected) ?? null

  return (
    <>
      <div className="row-between">
        <h2 className="mb-0">Rules</h2>
        <span className="small muted">{catalogue.count} documented ids</span>
      </div>
      <p className="muted">
        Every id this tool can emit, with what it means and what to do.{' '}
        <code>devrepro explain &lt;rule-id&gt;</code> prints any one of them in a terminal.
      </p>

      <div className="card">
        <input
          className="input"
          placeholder="Search ids, meanings and fixes…"
          aria-label="Search the rule catalogue"
          value={query}
          onChange={(e) => update('q', e.target.value)}
        />
        <div className="row mt-4 wrap">
          <label className={prefix === '' ? 'chip chip-on' : 'chip'}>
            <input
              type="radio"
              name="pack"
              checked={prefix === ''}
              onChange={() => update('pack', null)}
            />
            all
            <span className="chip-count">{RULES.length}</span>
          </label>
          {PREFIXES.map((p) => (
            <label key={p} className={prefix === p ? 'chip chip-on' : 'chip'}>
              <input
                type="radio"
                name="pack"
                checked={prefix === p}
                onChange={() => update('pack', p)}
              />
              {p}
              <span className="chip-count">{RULES.filter((r) => r.prefix === p).length}</span>
            </label>
          ))}
        </div>
        <p className="tiny muted mt-4 mb-0">
          Showing {visible.length} of {RULES.length}. Filters are in the URL, so a rule can be
          linked to.
        </p>
      </div>

      {active && (
        <article className="card enter" aria-labelledby="rule-detail">
          <div className="row-between">
            <h3 id="rule-detail" className="mb-0">
              <code>{active.rule_id}</code>
            </h3>
            <div className="row">
              <CopyButton
                text={`devrepro explain ${active.rule_id}`}
                label="Copy explain command"
              />
              <button className="btn-ghost" onClick={() => update('rule', null)}>
                Close
              </button>
            </div>
          </div>
          <p className="lead">{active.title}</p>
          <dl className="kv">
            <div className="kv-row">
              <dt className="kv-key">What it means</dt>
              <dd className="kv-value">{active.means}</dd>
            </div>
            <div className="kv-row">
              <dt className="kv-key">Why it matters</dt>
              <dd className="kv-value">{active.matters}</dd>
            </div>
            <div className="kv-row">
              <dt className="kv-key">How to fix it</dt>
              <dd className="kv-value">{active.fix}</dd>
            </div>
          </dl>
          {active.composed && (
            <p className="tiny muted mb-0">
              The prefix of this id is decided at runtime — whichever tool or ecosystem it
              applied to — so this entry is representative rather than the only form it takes.
            </p>
          )}
        </article>
      )}

      {visible.length === 0 ? (
        <EmptyState
          what="matching rules"
          hint="Try a shorter search, or clear the pack filter above."
        />
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">What it means</th>
                <th scope="col">{report ? 'In this report' : 'No scan loaded'}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((rule) => {
                const count = seen(rule)
                return (
                  <tr
                    key={rule.rule_id}
                    className={rule.rule_id === selected ? 'row-selected' : undefined}
                  >
                    <th scope="row">
                      <button
                        className="link-inline"
                        onClick={() => update('rule', rule.rule_id)}
                        aria-expanded={rule.rule_id === selected}
                      >
                        <code>{rule.rule_id}</code>
                      </button>
                      {rule.composed && (
                        <span className="pill pill-muted" title="Prefix decided at runtime">
                          composed
                        </span>
                      )}
                    </th>
                    <td className="small">{rule.title}</td>
                    <td>
                      {count > 0 ? (
                        <span className="row">
                          <Badge state="INFO" />
                          <span className="small">{count}×</span>
                        </span>
                      ) : (
                        <span className="small subtle">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
