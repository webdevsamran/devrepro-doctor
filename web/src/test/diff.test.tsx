/**
 * Environment diff viewer.
 *
 * The old page rendered every entry flat, keyed by array index, including the
 * ones classified `same`. These tests hold the three properties that make the
 * rebuild a diff viewer rather than a data dump: identical entries stay out of
 * the way by default, the filters live in the URL so a view can be sent to
 * someone, and rows that share a component and name still get distinct keys.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { DiffPage, diffToMarkdown, entryKey } from '../pages/diff'
import type { DiffEntry, EnvironmentDiff } from '../types'

function entry(overrides: Partial<DiffEntry> = {}): DiffEntry {
  return {
    component: 'toolchain',
    name: 'node',
    classification: 'version-drift',
    a_value: '20.11.0',
    b_value: '24.19.0',
    project_critical: false,
    ...overrides,
  }
}

function diff(entries: DiffEntry[]): EnvironmentDiff {
  return { a_snapshot_id: 'snap-a', b_snapshot_id: 'snap-b', entries }
}

/**
 * The page reads its file from an <input type="file">, so a test has to hand it
 * one. `userEvent.upload` needs a real File, and jsdom's File.text() works.
 */
async function loadDiff(user: ReturnType<typeof userEvent.setup>, payload: EnvironmentDiff) {
  const file = new File([JSON.stringify(payload)], 'diff.json', { type: 'application/json' })
  await user.upload(screen.getByLabelText('Diff JSON file'), file)
}

function renderPage(initial = '/diff') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <DiffPage />
    </MemoryRouter>,
  )
}

describe('environment diff viewer', () => {
  it('gives rows sharing a component and name distinct keys', () => {
    // A PATH-precedence entry names the same binary once per position, so
    // component+name alone repeats within one diff.
    const a = entry({ classification: 'path-precedence', name: 'python' })
    const b = entry({ classification: 'path-precedence', name: 'python' })
    expect(entryKey(a, 0)).not.toBe(entryKey(b, 1))
    expect(entryKey(a, 0)).toBe(entryKey(a, 0))
  })

  it('asks for a file before it has one', () => {
    renderPage()
    expect(screen.getByLabelText('Diff JSON file')).toBeInTheDocument()
    expect(screen.getByText(/never uploaded/i)).toBeInTheDocument()
  })

  it('rejects a file that is not a diff, by name, without crashing', async () => {
    // A truncated or conflict-marked export is the realistic version of this:
    // the extension is right and the contents are not.
    const user = userEvent.setup()
    renderPage()
    const file = new File(['{ not json at all'], 'notes.json', { type: 'application/json' })
    await user.upload(screen.getByLabelText('Diff JSON file'), file)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('notes.json')
    expect(alert).toHaveTextContent('devrepro diff')
  })

  it('rejects valid JSON that is not a diff', async () => {
    const user = userEvent.setup()
    renderPage()
    const file = new File([JSON.stringify({ hello: 'world' })], 'other.json', {
      type: 'application/json',
    })
    await user.upload(screen.getByLabelText('Diff JSON file'), file)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('hides identical entries by default and counts them anyway', async () => {
    const user = userEvent.setup()
    renderPage()
    await loadDiff(
      user,
      diff([
        entry({ name: 'node' }),
        entry({ name: 'git', classification: 'same', a_value: '2.4', b_value: '2.4' }),
      ]),
    )

    expect(await screen.findByText('node')).toBeInTheDocument()
    expect(screen.queryByText('git')).not.toBeInTheDocument()

    // Filtered out of the table, still present in its chip's count.
    // Queried by role: `Identical` also appears in the stacked bar's legend,
    // so matching on text alone finds two legitimate elements.
    const chip = screen.getByRole('checkbox', { name: /Identical/ }).closest('label')
    expect(chip).not.toBeNull()
    expect(within(chip as HTMLElement).getByText('1')).toBeInTheDocument()
  })

  it('reads the active classifications from the URL', async () => {
    const user = userEvent.setup()
    renderPage('/diff?kind=same')
    await loadDiff(
      user,
      diff([
        entry({ name: 'node' }),
        entry({ name: 'git', classification: 'same', a_value: '2.4', b_value: '2.4' }),
      ]),
    )
    expect(await screen.findByText('git')).toBeInTheDocument()
    expect(screen.queryByText('node')).not.toBeInTheDocument()
  })

  it('reads the search query from the URL', async () => {
    const user = userEvent.setup()
    renderPage('/diff?q=node')
    await loadDiff(user, diff([entry({ name: 'node' }), entry({ name: 'cargo' })]))
    expect(await screen.findByText('node')).toBeInTheDocument()
    expect(screen.queryByText('cargo')).not.toBeInTheDocument()
  })

  it('reads the project-critical filter from the URL', async () => {
    const user = userEvent.setup()
    renderPage('/diff?critical=1')
    await loadDiff(
      user,
      diff([
        entry({ name: 'node', project_critical: true }),
        entry({ name: 'cargo', project_critical: false }),
      ]),
    )
    expect(await screen.findByText('node')).toBeInTheDocument()
    expect(screen.queryByText('cargo')).not.toBeInTheDocument()
  })

  it('groups by classification, most alarming first', async () => {
    const user = userEvent.setup()
    renderPage()
    await loadDiff(
      user,
      diff([
        entry({ name: 'cargo', classification: 'version-drift' }),
        entry({ name: 'docker', classification: 'project-critical', project_critical: true }),
      ]),
    )

    await screen.findByText('cargo')
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent ?? '')
    expect(headings[0]).toContain('Project critical')
    expect(headings[1]).toContain('Version drift')
  })

  it('puts project-critical rows first inside their group', async () => {
    const user = userEvent.setup()
    renderPage()
    await loadDiff(
      user,
      diff([
        entry({ component: 'a-first', name: 'ordinary', project_critical: false }),
        entry({ component: 'z-last', name: 'critical-one', project_critical: true }),
      ]),
    )

    await screen.findByText('ordinary')
    const rowHeaders = screen.getAllByRole('rowheader').map((el) => el.textContent ?? '')
    expect(rowHeaders[0]).toContain('critical-one')
  })

  it('toggling a classification changes what is shown', async () => {
    const user = userEvent.setup()
    renderPage()
    await loadDiff(
      user,
      diff([entry({ name: 'git', classification: 'same', a_value: '2.4', b_value: '2.4' })]),
    )

    await screen.findByRole('checkbox', { name: /Identical/ })
    expect(screen.queryByText('git')).not.toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: /Identical/ }))

    expect(screen.getByText('git')).toBeInTheDocument()
  })

  it('says so when every classification is filtered out', async () => {
    const user = userEvent.setup()
    renderPage('/diff?kind=missing')
    await loadDiff(user, diff([entry({ name: 'node' })]))
    expect(await screen.findByText(/no matching entries/i)).toBeInTheDocument()
  })

  it('names both snapshots so the direction is unambiguous', async () => {
    const user = userEvent.setup()
    renderPage()
    await loadDiff(user, diff([entry()]))
    expect(await screen.findByText('snap-a')).toBeInTheDocument()
    expect(screen.getByText('snap-b')).toBeInTheDocument()
  })

  it('offers the visible rows as Markdown', async () => {
    const user = userEvent.setup()
    renderPage()
    await loadDiff(user, diff([entry()]))
    expect(await screen.findByRole('button', { name: /copy as markdown/i })).toBeInTheDocument()
  })
})

describe('diff markdown', () => {
  it('escapes pipes so a PATH value cannot break the table', () => {
    const markdown = diffToMarkdown([entry({ name: 'PATH', a_value: 'a|b', b_value: 'c' })])
    expect(markdown).toContain('a\\|b')
  })

  it('marks project-critical rows', () => {
    expect(diffToMarkdown([entry({ project_critical: true })])).toContain('⚠️')
  })

  it('renders an em dash for a value that is absent on one side', () => {
    const markdown = diffToMarkdown([entry({ a_value: undefined })])
    expect(markdown).toContain('| — |')
  })
})
