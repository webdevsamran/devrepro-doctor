/**
 * Navigation model, routing coverage and the command palette.
 *
 * The console used to keep its navigation in three places at once: a flat
 * `NAV` array in App.tsx, a thirty-two branch render chain beside it, and a
 * Python test that parsed the array out of the TSX. `nav.ts` is now the single
 * source of truth, and these tests hold the router to it.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { CommandPalette } from '../components/CommandPalette'
import { ALL_ITEMS, GROUP_OF, NAV_GROUPS, itemById, searchItems } from '../nav'
import { PLAIN_PAGES, REPORT_PAGES } from '../routes'

describe('navigation model', () => {
  it('gives every item a unique id', () => {
    const ids = ALL_ITEMS.map((i) => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('assigns every item to exactly one group', () => {
    for (const item of ALL_ITEMS) {
      expect(GROUP_OF[item.id]).toBeTruthy()
    }
    const fromGroups = NAV_GROUPS.flatMap((g) => g.items)
    expect(fromGroups).toHaveLength(ALL_ITEMS.length)
  })

  it('routes every navigable item', () => {
    // A sidebar entry with no route renders the not-found page: the link is
    // visible, clickable, and wrong. Home is handled by its own route because
    // it takes a callback rather than the report.
    const routed = new Set([...Object.keys(REPORT_PAGES), ...Object.keys(PLAIN_PAGES), 'home'])
    const unrouted = ALL_ITEMS.map((i) => i.id).filter((id) => !routed.has(id))
    expect(unrouted).toEqual([])
  })

  it('does not route anything the sidebar cannot reach', () => {
    const navigable = new Set(ALL_ITEMS.map((i) => i.id))
    const orphans = [...Object.keys(REPORT_PAGES), ...Object.keys(PLAIN_PAGES)].filter(
      (id) => !navigable.has(id),
    )
    expect(orphans).toEqual([])
  })

  it('resolves an item by id', () => {
    expect(itemById('findings')?.label).toBe('Findings')
    expect(itemById('nope')).toBeUndefined()
  })
})

describe('palette search ranking', () => {
  it('returns everything for an empty query', () => {
    expect(searchItems('')).toHaveLength(ALL_ITEMS.length)
  })

  it('puts a label prefix match first', () => {
    // "PATH Explorer" must beat "Ports & Services", which merely contains a
    // matching keyword — otherwise typing the exact name still needs arrowing.
    expect(searchItems('path')[0].id).toBe('path')
  })

  it('matches on keywords the label does not contain', () => {
    expect(searchItems('cuda').map((i) => i.id)).toContain('gpustack')
    expect(searchItems('docker').map((i) => i.id)).toContain('containers')
  })

  it('returns nothing for a query that matches nothing', () => {
    expect(searchItems('zzzzznotathing')).toEqual([])
  })
})

function renderPalette(onClose = vi.fn()) {
  return {
    onClose,
    ...render(
      <MemoryRouter>
        <CommandPalette open onClose={onClose} />
      </MemoryRouter>,
    ),
  }
}

describe('CommandPalette', () => {
  it('renders nothing while closed', () => {
    const { container } = render(
      <MemoryRouter>
        <CommandPalette open={false} onClose={vi.fn()} />
      </MemoryRouter>,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('filters as the user types', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'drift')
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(1)
    expect(options[0]).toHaveTextContent('Drift Timeline')
  })

  it('says so when nothing matches', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.type(screen.getByRole('combobox'), 'zzzzz')
    expect(screen.queryAllByRole('option')).toHaveLength(0)
    expect(screen.getByText(/no view matches/i)).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const { onClose } = renderPalette()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('selects with Enter and closes', async () => {
    const user = userEvent.setup()
    const { onClose } = renderPalette()
    await user.type(screen.getByRole('combobox'), 'findings')
    await user.keyboard('{Enter}')
    expect(onClose).toHaveBeenCalled()
  })

  it('moves the selection with the arrow keys', async () => {
    const user = userEvent.setup()
    renderPalette()
    const first = screen.getAllByRole('option')[0]
    expect(first).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowDown}')
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'false')
    expect(options[1]).toHaveAttribute('aria-selected', 'true')
  })

  it('exposes the combobox relationship assistive tech needs', () => {
    renderPalette()
    const input = screen.getByRole('combobox')
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-controls', 'palette-list')
    // aria-activedescendant is what tells a screen reader which option is
    // highlighted while focus stays in the text field.
    expect(input).toHaveAttribute('aria-activedescendant')
  })
})
