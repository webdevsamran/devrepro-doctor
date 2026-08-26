/**
 * Unit tests for shared UI primitives.
 * Synthetic data only; no network access.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Badge, Card, ErrorState, Loading } from '../components/ui'

describe('Badge', () => {
  it('renders the state text with a state class', () => {
    render(<Badge state="BLOCKED" />)
    const badge = screen.getByText('BLOCKED')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('badge-blocked')
  })
})

describe('Card', () => {
  it('renders a title when given', () => {
    render(
      <Card title="Toolchains">
        <p>body</p>
      </Card>,
    )
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Toolchains')
    expect(screen.getByText('body')).toBeInTheDocument()
  })

  it('omits the heading when no title is given', () => {
    render(<Card>only body</Card>)
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  })
})

describe('Loading', () => {
  it('announces loading politely for assistive tech', () => {
    render(<Loading />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  })
})

describe('ErrorState', () => {
  it('shows the failure message and remediation guidance', () => {
    render(<ErrorState message="HTTP 404" />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('HTTP 404')).toBeInTheDocument()
    expect(screen.getByText(/devrepro serve/)).toBeInTheDocument()
  })
})
