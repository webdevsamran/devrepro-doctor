/**
 * The fleet version heatmap.
 *
 * The server has returned this data since it shipped and the page rendered it
 * as `3.11 ×4 · 3.12 ×2` — a sentence, which means reading every row to find
 * the one that matters. The entire value of a fleet view is seeing divergence
 * at a glance, and a list of counts is the one presentation that cannot do it.
 *
 * Two properties carry the weight, and both are ways this could quietly be
 * wrong rather than obviously broken:
 *
 * - Colour encodes *share*, not count. A team of four and a team of four
 *   hundred should look identical when equally divided; scaling by count makes
 *   every small team look healthy and every large one look alarming.
 * - Colour is never the only signal. This is the view people screenshot, and
 *   without the counts as text it is a grid of grey squares to a reader with a
 *   colour vision deficiency.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { VersionHeatmap } from '../components/charts'

describe('VersionHeatmap', () => {
  it('gives each version a share of the row rather than a fixed cell', () => {
    render(<VersionHeatmap heatmap={{ python: { '3.11': 3, '3.12': 1 } }} />)

    const cells = screen.getAllByRole('cell')
    expect(cells).toHaveLength(2)
    // 3 of 4 and 1 of 4 — the flex basis is what makes divergence visible.
    expect(cells[0].getAttribute('style')).toContain('0.75')
    expect(cells[1].getAttribute('style')).toContain('0.25')
  })

  it('scales by share so fleet size does not change the picture', () => {
    const { rerender } = render(<VersionHeatmap heatmap={{ node: { '20': 1, '22': 1 } }} />)
    const small = screen.getAllByRole('cell').map((c) => c.getAttribute('style'))

    rerender(<VersionHeatmap heatmap={{ node: { '20': 200, '22': 200 } }} />)
    const large = screen.getAllByRole('cell').map((c) => c.getAttribute('style'))

    expect(large).toEqual(small)
  })

  it('carries the count as text, not only as colour', () => {
    render(<VersionHeatmap heatmap={{ go: { '1.22': 7 } }} />)

    const cell = screen.getByRole('cell')
    expect(within(cell).getByText('7')).toBeInTheDocument()
    expect(within(cell).getByText('1.22')).toBeInTheDocument()
  })

  it('spells out the whole comparison in the title, for hover and screen readers', () => {
    render(<VersionHeatmap heatmap={{ python: { '3.11': 3, '3.12': 1 } }} />)

    expect(screen.getAllByRole('cell')[0]).toHaveAttribute(
      'title',
      'python 3.11: 3 of 4 machines (75%)',
    )
  })

  it('reads a converged tool as calm rather than as a full-intensity block', () => {
    render(<VersionHeatmap heatmap={{ git: { '2.45.1': 40 } }} />)

    expect(screen.getByRole('cell').className).toContain('is-converged')
    // Nothing diverged, so the "N versions" warning is absent.
    expect(screen.queryByText(/versions$/)).not.toBeInTheDocument()
  })

  it('says how many versions a diverged tool has', () => {
    render(<VersionHeatmap heatmap={{ python: { '3.11': 1, '3.12': 1, '3.13': 1 } }} />)

    expect(screen.getByText('3 versions')).toBeInTheDocument()
  })

  it('puts the most common version first', () => {
    render(<VersionHeatmap heatmap={{ node: { '18': 1, '22': 9 } }} />)

    const cells = screen.getAllByRole('cell')
    expect(within(cells[0]).getByText('22')).toBeInTheDocument()
  })

  it('renders nothing at all when the fleet is empty', () => {
    const { container } = render(<VersionHeatmap heatmap={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('is labelled as a table for assistive technology', () => {
    render(<VersionHeatmap heatmap={{ go: { '1.22': 1 } }} />)
    expect(screen.getByRole('table', { name: /tool versions/i })).toBeInTheDocument()
  })
})
