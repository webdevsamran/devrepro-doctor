/**
 * Containers & WSL.
 *
 * This view fetched `/api/containers-wsl`, an endpoint the server does not
 * implement, and fell back to an invented fixture on every load. A diagnostics
 * tool showing a plausible green container panel that describes nobody's
 * machine is worse than showing nothing, so these tests pin that it reads the
 * report and says so plainly when the report has nothing to read.
 */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ContainersWslPage } from '../pages/platform'
import type { ContainerState, ScanReport } from '../types'

function report(overrides: Partial<ScanReport> = {}): ScanReport {
  return {
    schema_version: '1.0',
    devrepro_version: '0.0.0',
    created_at: '2026-01-01T00:00:00Z',
    platform: { os_name: 'Darwin', os_version: '15', arch: 'arm64' },
    findings: [],
    tools: [],
    requirements: [],
    probe_errors: [],
    privacy: {},
    ...overrides,
  } as ScanReport
}

function containers(overrides: Partial<ContainerState> = {}): ContainerState {
  return { docker_daemon_ok: true, ...overrides }
}

function renderPage(scan: ScanReport) {
  return render(
    <MemoryRouter>
      <ContainersWslPage report={scan} />
    </MemoryRouter>,
  )
}

describe('containers view', () => {
  it('names the engine behind docker, not just the daemon state', () => {
    renderPage(
      report({
        containers: containers({ backend: 'colima', server_version: '26.1.3' }),
      }),
    )
    expect(screen.getByText('Colima')).toBeInTheDocument()
    expect(screen.getByText('26.1.3')).toBeInTheDocument()
  })

  it('says the engine is unidentified rather than inventing one', () => {
    renderPage(report({ containers: containers({ backend: null }) }))
    expect(screen.getByText(/engine not identified/i)).toBeInTheDocument()
  })

  it('shows the endpoint kind and states that the socket path is not collected', () => {
    // The privacy claim, made where someone reading the value can see it: a
    // Colima socket path contains the username and never leaves the machine.
    renderPage(report({ containers: containers({ endpoint_kind: 'unix', context_name: 'colima' }) }))
    expect(screen.getByText(/via unix/)).toBeInTheDocument()
    expect(screen.getByText(/socket path is never collected/i)).toBeInTheDocument()
  })

  it('marks an emulated engine', () => {
    renderPage(
      report({
        platform: { os_name: 'Darwin', os_version: '15', arch: 'arm64' },
        containers: containers({ server_arch: 'x86_64' }),
      }),
    )
    expect(screen.getByText('emulated')).toBeInTheDocument()
  })

  it('does not mark a matching architecture as emulated', () => {
    // Python reports `AMD64` where docker reports `x86_64`; comparing them raw
    // would label every Windows machine as emulating itself.
    renderPage(
      report({
        platform: { os_name: 'Windows', os_version: '11', arch: 'AMD64' },
        containers: containers({ server_arch: 'x86_64' }),
      }),
    )
    expect(screen.queryByText('emulated')).not.toBeInTheDocument()
  })

  it('formats reclaimable space in the decimal units docker prints', () => {
    renderPage(report({ containers: containers({ reclaimable_bytes: 44_593_000_000 }) }))
    expect(screen.getByText('44.6 GB')).toBeInTheDocument()
  })

  it('offers the prune command without ever running it', () => {
    renderPage(report({ containers: containers({ reclaimable_bytes: 44_593_000_000 }) }))
    expect(screen.getByText(/docker system prune/)).toBeInTheDocument()
    expect(screen.getByText(/never runs it/i)).toBeInTheDocument()
  })

  it('says nothing about pruning when there is nothing to reclaim', () => {
    renderPage(report({ containers: containers({ reclaimable_bytes: null }) }))
    expect(screen.queryByText(/docker system prune/)).not.toBeInTheDocument()
  })

  it('explains why a second engine matters', () => {
    renderPage(report({ containers: containers({ other_runtimes: ['Colima', 'Podman'] }) }))
    expect(screen.getByText('Colima')).toBeInTheDocument()
    expect(screen.getByText(/docker context/)).toBeInTheDocument()
  })

  it('does not warn about context when only one engine is installed', () => {
    renderPage(report({ containers: containers({ other_runtimes: ['Podman'] }) }))
    expect(screen.queryByText(/load-bearing/)).not.toBeInTheDocument()
  })

  it('lists the container findings from the report', () => {
    renderPage(
      report({
        containers: containers(),
        findings: [
          {
            rule_id: 'containers/cgroup-v1',
            state: 'WARN',
            summary: 'Container engine is using cgroup v1.',
            evidence: [{ source: 'command' }],
          },
          {
            rule_id: 'path/duplicates',
            state: 'WARN',
            summary: 'not a container finding',
            evidence: [{ source: 'env' }],
          },
        ],
      }),
    )
    expect(screen.getByText('containers/cgroup-v1')).toBeInTheDocument()
    expect(screen.queryByText('not a container finding')).not.toBeInTheDocument()
  })

  it('says the report carries no container state rather than showing zeroes', () => {
    // Zeroes would read as "nothing to reclaim, no engine", which is a
    // different and false claim.
    renderPage(report({ containers: null }))
    expect(screen.getByText(/no container state/i)).toBeInTheDocument()
    expect(screen.getByText(/devrepro scan/)).toBeInTheDocument()
  })

  it('reports WSL as unavailable rather than omitting the section', () => {
    renderPage(report({ containers: containers(), wsl: { available: false } }))
    expect(screen.getByText(/WSL is not available/i)).toBeInTheDocument()
  })

  it('lists WSL distributions when they exist', () => {
    renderPage(
      report({
        containers: containers(),
        wsl: { available: true, version: '2', distros: ['Ubuntu', 'docker-desktop'] },
      }),
    )
    const wslCard = screen.getByRole('heading', { name: 'WSL' }).closest('section')
    expect(wslCard).not.toBeNull()
    expect(within(wslCard as HTMLElement).getByText(/Ubuntu, docker-desktop/)).toBeInTheDocument()
  })
})
