/**
 * The rule catalogue.
 *
 * This page listed the packs that happened to appear in the current report --
 * a handful of cards with a count on each. That answers "what did this scan
 * touch", which Findings answers better, and cannot answer the question
 * someone arrives with: what does `containers/cgroup-v1` mean and what do I do.
 *
 * Two properties matter beyond the search working. The catalogue is
 * documentation, so it renders without a scan rather than telling the visitor
 * the console is unavailable. And "this rule did not fire" and "no scan has
 * run" are different facts, so the cross-reference column says which it is.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import catalogue from '../data/rules.json' with { type: 'json' }
import { RulesPage } from '../pages/rules'
import type { Finding, ScanReport } from '../types'

function report(findings: Finding[] = []): ScanReport {
  return {
    schema_version: '1.0',
    devrepro_version: '0.0.0',
    created_at: '2026-01-01T00:00:00Z',
    platform: { os_name: 'Linux', os_version: '1', arch: 'x86_64' },
    findings,
    tools: [],
    requirements: [],
    probe_errors: [],
    privacy: {},
  } as unknown as ScanReport
}

function finding(rule_id: string): Finding {
  return {
    rule_id,
    state: 'WARN',
    summary: 'something',
    evidence: [{ source: 'system' }],
  } as Finding
}

function renderPage(scan?: ScanReport, initial = '/rules') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <RulesPage report={scan} />
    </MemoryRouter>,
  )
}

describe('rule catalogue', () => {
  it('renders without a scan, because it is documentation', () => {
    renderPage(undefined)
    expect(screen.getByRole('heading', { name: 'Rules' })).toBeInTheDocument()
    expect(screen.getByText(`${catalogue.count} documented ids`)).toBeInTheDocument()
  })

  it('says no scan is loaded rather than showing zeroes', () => {
    // Zeroes would read as "none of these rules fired", which is a claim the
    // page is in no position to make.
    renderPage(undefined)
    expect(screen.getByRole('columnheader', { name: /no scan loaded/i })).toBeInTheDocument()
  })

  it('switches the column heading once a report is present', () => {
    renderPage(report())
    expect(screen.getByRole('columnheader', { name: /in this report/i })).toBeInTheDocument()
  })

  it('searches meanings and fixes, not just ids', () => {
    renderPage(undefined, '/rules?q=pointer files')
    // `git/lfs-required-not-installed` never contains "pointer" in its id.
    expect(screen.getByText('git/lfs-required-not-installed')).toBeInTheDocument()
  })

  it('reads the search query from the URL', () => {
    renderPage(undefined, '/rules?q=cgroup')
    expect(screen.getByText('containers/cgroup-v1')).toBeInTheDocument()
    expect(screen.queryByText('git/shallow-clone')).not.toBeInTheDocument()
  })

  it('reads the pack filter from the URL', () => {
    renderPage(undefined, '/rules?pack=hygiene')
    const rows = screen.getAllByRole('rowheader')
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) expect(row.textContent).toMatch(/^hygiene\//)
  })

  it('opens a rule detail from the URL', () => {
    renderPage(undefined, '/rules?rule=containers/cgroup-v1')
    const detail = screen.getByLabelText('containers/cgroup-v1')
    expect(within(detail).getByText(/first-generation cgroup/i)).toBeInTheDocument()
    expect(within(detail).getByText(/unified cgroups/i)).toBeInTheDocument()
  })

  it('offers the explain command for the open rule', () => {
    renderPage(undefined, '/rules?rule=containers/cgroup-v1')
    expect(
      screen.getByRole('button', { name: /copy explain command/i }),
    ).toBeInTheDocument()
  })

  it('clicking a rule opens its detail', async () => {
    const user = userEvent.setup()
    renderPage(undefined, '/rules?q=cgroup')
    await user.click(screen.getByRole('button', { name: 'containers/cgroup-v1' }))
    expect(screen.getByLabelText('containers/cgroup-v1')).toBeInTheDocument()
  })

  it('marks composed ids, whose prefix is a runtime value', () => {
    // Someone who does not know this searches for `uv/multiple-installations`,
    // fails to find it, and concludes the catalogue is incomplete.
    renderPage(undefined, '/rules?q=multiple-installations')
    expect(screen.getAllByText('composed').length).toBeGreaterThan(0)
  })

  it('counts a composed id against its representative entry', () => {
    // The report emits `uv/multiple-installations`; the catalogue documents
    // one representative prefix. Keying only on the exact string would show a
    // dash beside a rule that fired eight times.
    renderPage(report([finding('uv/multiple-installations')]), '/rules?q=multiple-installations')
    expect(screen.getAllByText('1×').length).toBeGreaterThan(0)
  })

  it('counts an exact id match', () => {
    renderPage(report([finding('containers/cgroup-v1')]), '/rules?q=cgroup')
    expect(screen.getByText('1×')).toBeInTheDocument()
  })

  it('shows a dash for a rule this report did not emit', () => {
    renderPage(report([]), '/rules?q=cgroup')
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('says so when the search matches nothing', () => {
    renderPage(undefined, '/rules?q=zzzzz-no-such-rule')
    expect(screen.getByText(/no matching rules/i)).toBeInTheDocument()
  })
})

describe('the generated catalogue', () => {
  it('is not empty and agrees with its own count', () => {
    // Generated by `scripts/generate_rule_docs.py` from the Python catalogue,
    // with a `--check` gate in CI. This guards against the import silently
    // resolving to an empty object.
    expect(catalogue.rules.length).toBe(catalogue.count)
    expect(catalogue.count).toBeGreaterThan(50)
  })

  it('gives every rule the four fields the page renders', () => {
    for (const rule of catalogue.rules) {
      expect(rule.rule_id).toMatch(/^[a-z0-9-]+\/[a-z0-9-]+$/)
      expect(rule.title.length).toBeGreaterThan(3)
      expect(rule.means.length).toBeGreaterThan(20)
      expect(rule.fix.length).toBeGreaterThan(3)
    }
  })

  it('splits every id into the prefix and suffix the filters use', () => {
    for (const rule of catalogue.rules) {
      expect(`${rule.prefix}/${rule.suffix}`).toBe(rule.rule_id)
    }
  })
})
