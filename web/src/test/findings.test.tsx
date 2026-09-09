/**
 * Findings triage.
 *
 * Two things are load-bearing here. Filters live in the URL, because "look at
 * this" is most of what anyone does with a findings list and a link that
 * reopens someone else's view beats describing it. And keys are unique, because
 * rule ids are not: a single scan emits `env/credential-names-present` twice,
 * and keying the list by rule id gave React duplicate keys, which misassociates
 * component state -- an open evidence drawer jumps to a different finding.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { FindingsPage, findingKey } from '../pages/core'
import type { Finding, ScanReport } from '../types'

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    rule_id: 'path/duplicates',
    state: 'WARN',
    summary: 'duplicate entries',
    evidence: [{ source: 'env', redacted: true }],
    references: [],
    ...overrides,
  } as Finding
}

function report(findings: Finding[]): ScanReport {
  return {
    schema_version: '1.0',
    devrepro_version: '0.0.0',
    created_at: '2026-01-01T00:00:00Z',
    platform: { os_name: 'Linux', os_version: '1', arch: 'x86_64' },
    findings,
    tools: [],
    requirements: [],
    policy_applied: false,
    probe_errors: [],
    privacy: {},
  } as unknown as ScanReport
}

function renderPage(findings: Finding[], initial = '/findings') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <FindingsPage report={report(findings)} />
    </MemoryRouter>,
  )
}

describe('findings triage', () => {
  it('gives findings that share a rule id distinct keys', () => {
    // A real scan emits `env/credential-names-present` twice, so keying the
    // list by rule id hands React duplicate keys.
    //
    // Asserted on the key function rather than on a console warning: React
    // deduplicates its warnings, so a test that watched console.error passed
    // happily with the bug reintroduced. Checking the value directly is the
    // difference between a regression test and a reassuring one.
    const a = finding({ rule_id: 'env/credential-names-present', summary: 'first' })
    const b = finding({ rule_id: 'env/credential-names-present', summary: 'second' })

    expect(findingKey(a, 0)).not.toBe(findingKey(b, 1))
    expect(findingKey(a, 0)).toBe(findingKey(a, 0))
  })

  it('renders both findings that share a rule id', () => {
    renderPage([
      finding({ rule_id: 'env/credential-names-present', summary: 'first' }),
      finding({ rule_id: 'env/credential-names-present', summary: 'second' }),
    ])
    expect(screen.getByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('shows only the severities selected by default', () => {
    renderPage([
      finding({ rule_id: 'a/blocked', state: 'BLOCKED', summary: 'blocked one' }),
      finding({ rule_id: 'b/pass', state: 'PASS', summary: 'passing one' }),
    ])
    expect(screen.getByText('blocked one')).toBeInTheDocument()
    expect(screen.queryByText('passing one')).not.toBeInTheDocument()
  })

  it('reads the active severities from the URL', () => {
    renderPage(
      [finding({ rule_id: 'b/pass', state: 'PASS', summary: 'passing one' })],
      '/findings?state=PASS',
    )
    expect(screen.getByText('passing one')).toBeInTheDocument()
  })

  it('reads the search query from the URL', () => {
    renderPage(
      [
        finding({ rule_id: 'a/one', summary: 'alpha problem' }),
        finding({ rule_id: 'b/two', summary: 'beta problem' }),
      ],
      '/findings?q=alpha',
    )
    expect(screen.getByText('alpha problem')).toBeInTheDocument()
    expect(screen.queryByText('beta problem')).not.toBeInTheDocument()
  })

  it('orders the most severe first', () => {
    renderPage(
      [
        finding({ rule_id: 'c/warn', state: 'WARN', summary: 'a warning' }),
        finding({ rule_id: 'a/blocked', state: 'BLOCKED', summary: 'a blocker' }),
      ],
      '/findings?state=BLOCKED,WARN',
    )
    const rendered = screen.getAllByRole('article').map((el) => el.textContent ?? '')
    expect(rendered[0]).toContain('a blocker')
  })

  it('groups by component when asked', () => {
    renderPage(
      [
        finding({ rule_id: 'a/one', component: 'docker', summary: 'docker thing' }),
        finding({ rule_id: 'b/two', component: 'python', summary: 'python thing' }),
      ],
      '/findings?state=WARN&group=component',
    )
    expect(screen.getByRole('heading', { name: /docker/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /python/ })).toBeInTheDocument()
  })

  it('counts every severity, including ones filtered out', () => {
    renderPage([
      finding({ rule_id: 'a/one', state: 'PASS' }),
      finding({ rule_id: 'b/two', state: 'PASS' }),
      finding({ rule_id: 'c/three', state: 'WARN' }),
    ])
    const passChip = screen.getByText('PASS').closest('label')
    expect(passChip).not.toBeNull()
    expect(within(passChip as HTMLElement).getByText('2')).toBeInTheDocument()
  })

  it('toggling a severity updates what is shown', async () => {
    const user = userEvent.setup()
    renderPage([finding({ rule_id: 'b/pass', state: 'PASS', summary: 'passing one' })])
    expect(screen.queryByText('passing one')).not.toBeInTheDocument()

    await user.click(screen.getByText('PASS'))

    expect(screen.getByText('passing one')).toBeInTheDocument()
  })

  it('says so when everything is filtered out', () => {
    renderPage([finding({ state: 'PASS' })], '/findings?state=BLOCKED')
    expect(screen.getByText(/no matching findings/i)).toBeInTheDocument()
  })

  it('offers the visible findings as Markdown for an issue report', () => {
    renderPage([finding({ rule_id: 'a/one', summary: 'something' })])
    expect(screen.getByRole('button', { name: /copy as markdown/i })).toBeInTheDocument()
  })
})
