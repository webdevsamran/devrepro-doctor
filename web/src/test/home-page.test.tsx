/**
 * Unit tests for the Home page hero and CLI quickstart block.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { HomePage } from '../pages/core'

describe('HomePage', () => {
  it('renders the product promise and privacy points', () => {
    render(<HomePage onStart={() => {}} />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('DevRepro Doctor')
    expect(screen.getByText(/No cloud, no telemetry/)).toBeInTheDocument()
    expect(screen.getByText(/Read-only by default/)).toBeInTheDocument()
  })

  it('navigates to the machine overview on click', () => {
    const onStart = vi.fn()
    render(<HomePage onStart={onStart} />)
    fireEvent.click(screen.getByRole('button', { name: /Open machine overview/ }))
    expect(onStart).toHaveBeenCalledOnce()
  })

  it('shows the 60-second CLI quickstart commands', () => {
    render(<HomePage onStart={() => {}} />)
    expect(screen.getByText(/devrepro doctor/)).toBeInTheDocument()
  })
})
