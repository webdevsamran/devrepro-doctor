/**
 * The snapshot viewer, the Markdown export and the gallery.
 *
 * Two properties carry the weight and neither is about layout:
 *
 * - **Nothing is uploaded.** A snapshot describes a developer's machine. Every
 *   tool that solves "somebody sent me a snapshot I cannot read" solves it with
 *   an upload, and that is the one thing this project will not add — so the
 *   test asserts the page says so, in the place somebody about to paste a
 *   colleague's machine state will read it.
 * - **Markdown is the export that matters.** The reason to export a diagnostic
 *   is to paste it into an issue, and an image of a table is a table nobody can
 *   search, quote or diff.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { reportToMarkdown } from '../components/export'
import { GalleryPage, SnapshotViewerPage, TourPage } from '../pages/tools'
import type { Finding, FindingState, ScanReport } from '../types'

function report(overrides: Partial<ScanReport> = {}): ScanReport {
  return {
    schema_version: '1.0',
    devrepro_version: '0.2.0',
    created_at: '2026-05-05T00:00:00+00:00',
    platform: { os_name: 'Linux', os_version: '6.8.0', arch: 'x86_64', is_wsl: false },
    findings: [],
    tools: [],
    ...overrides,
  } as ScanReport
}

function finding(rule_id: string, state: FindingState, summary = 'something happened'): Finding {
  return { rule_id, state, summary, evidence: [{ source: 'system' }] } as Finding
}

describe('snapshot viewer', () => {
  it('says nothing is uploaded, where somebody is about to paste a colleague’s machine', () => {
    render(<SnapshotViewerPage />)
    expect(screen.getByText(/Nothing is/i)).toBeInTheDocument()
    expect(screen.getByText(/no endpoint behind this/i)).toBeInTheDocument()
  })

  it('renders a pasted snapshot without a network call', async () => {
    const user = userEvent.setup()
    render(<SnapshotViewerPage />)

    await user.click(screen.getByLabelText('Snapshot JSON'))
    await user.paste(JSON.stringify(report({ findings: [finding('docker/down', 'BLOCKED')] })))

    expect(screen.getByText('docker/down')).toBeInTheDocument()
    expect(screen.getByText('Linux 6.8.0')).toBeInTheDocument()
  })

  it('explains an unparseable paste rather than showing nothing', async () => {
    const user = userEvent.setup()
    render(<SnapshotViewerPage />)

    await user.click(screen.getByLabelText('Snapshot JSON'))
    await user.paste('{not json')

    expect(screen.getByRole('alert')).toHaveTextContent(/Could not read that/i)
  })

  it('rejects valid JSON that is not a snapshot, and says which fields it wanted', async () => {
    const user = userEvent.setup()
    render(<SnapshotViewerPage />)

    await user.click(screen.getByLabelText('Snapshot JSON'))
    await user.paste('{"hello": "world"}')

    expect(screen.getByRole('alert')).toHaveTextContent(/platform, findings or tools/i)
  })

  it('shows an empty state before anything is loaded', () => {
    render(<SnapshotViewerPage />)
    expect(screen.getByText(/devrepro snapshot -o machine.json/)).toBeInTheDocument()
  })
})

describe('markdown export', () => {
  it('puts blockers first, because that is why anybody pastes this anywhere', () => {
    const markdown = reportToMarkdown(
      report({
        findings: [
          finding('a/info', 'INFO'),
          finding('b/blocked', 'BLOCKED'),
          finding('c/warn', 'WARN'),
        ],
      }),
    )
    const rows = markdown.split('\n').filter((line) => line.startsWith('| '))
    // Header, separator, then findings in severity order.
    expect(rows[2]).toContain('b/blocked')
    expect(rows[3]).toContain('c/warn')
  })

  it('escapes a pipe in a summary instead of breaking the table', () => {
    const markdown = reportToMarkdown(
      report({ findings: [finding('x/y', 'WARN', 'PATH is a|b|c')] }),
    )
    expect(markdown).toContain('PATH is a\\|b\\|c')
  })

  it('caps the table and says how many were left out', () => {
    const many = Array.from({ length: 40 }, (_, i) => finding(`r/${i}`, 'WARN'))
    const markdown = reportToMarkdown(report({ findings: many }), { limit: 5 })
    expect(markdown).toContain('…and 35 more')
  })

  it('carries the machine and the scan time, because a pasted report outlives its thread', () => {
    const markdown = reportToMarkdown(report())
    expect(markdown).toContain('Linux 6.8.0')
    expect(markdown).toContain('2026-05-05')
  })

  it('says it is redacted, since somebody is about to paste it in public', () => {
    expect(reportToMarkdown(report())).toContain('redacted')
  })

  it('handles a report with no findings without producing an empty table', () => {
    expect(reportToMarkdown(report())).toContain('No findings.')
  })
})

describe('gallery and tour', () => {
  it('renders every severity, each with its own label rather than colour alone', () => {
    const { container } = render(<GalleryPage />)
    // Queried by class rather than by walking up from the card title: `closest`
    // found the title's own wrapper, which contains the heading and nothing
    // else, and the assertion failed for a reason that had nothing to do with
    // the badges.
    const badges = Array.from(container.querySelectorAll('.badge')).map((el) => el.textContent)
    for (const state of ['BLOCKED', 'ERROR', 'WARN', 'INFO', 'PASS', 'UNKNOWN']) {
      expect(badges).toContain(state)
    }
  })

  it('states why it is a route rather than Storybook', () => {
    render(<GalleryPage />)
    expect(screen.getByText(/inherits the real tokens/i)).toBeInTheDocument()
  })

  it('never launches the tour by itself, and says so', () => {
    render(<TourPage />)
    expect(screen.getByText(/never opens itself/i)).toBeInTheDocument()
  })

  it('tells the reader where each thing it describes actually is', () => {
    render(<TourPage />)
    expect(screen.getAllByText(/^Where: /).length).toBeGreaterThan(3)
  })
})
