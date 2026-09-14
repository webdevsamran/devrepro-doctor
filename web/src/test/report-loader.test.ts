/**
 * Unit tests for the report loader's source-priority contract:
 * ?src= override first, then /api/report, then ./report.json.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { loadReport } from '../api/report'
import type { ScanReport } from '../types'

const fakeReport = {
  devrepro_version: '0.1.0',
  platform: { os_name: 'TestOS', os_version: '1.0', arch: 'x86_64' },
  findings: [],
} as unknown as ScanReport

function mockFetchSequence(responses: Record<string, { ok: boolean; status?: number; body?: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const r = responses[url]
      if (!r) return new Response('', { status: 404 })
      return new Response(r.ok ? JSON.stringify(r.body) : '', {
        status: r.ok ? 200 : (r.status ?? 500),
      })
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.location.hash = ''
})

describe('loadReport source priority', () => {
  it('uses the ?src= override when present', async () => {
    window.history.replaceState(null, '', '/?src=custom.json')
    // Keyed on the URL that is actually requested, not on the string in the
    // query. The override is resolved against the page before it reaches
    // `fetch`, so that what gets fetched is the thing that was security-checked
    // rather than a second resolution nobody saw.
    const requested = new URL('custom.json', window.location.href).href
    mockFetchSequence({ [requested]: { ok: true, body: fakeReport } })
    await expect(loadReport()).resolves.toEqual(fakeReport)
    window.history.replaceState(null, '', '/')
  })

  it('ignores a ?src= pointing at another origin', async () => {
    // The alert CodeQL raised, as a behaviour. A link carrying this parameter
    // made the console fetch someone else's JSON and render it as a reading of
    // the reader's own machine -- a confident, authoritative, fabricated
    // diagnosis. Refused, the page falls through to its real sources.
    window.history.replaceState(null, '', '/?src=https://example.invalid/clean.json')
    mockFetchSequence({ './report.json': { ok: true, body: fakeReport } })

    await expect(loadReport()).resolves.toEqual(fakeReport)

    const urls = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0])
    expect(urls.some((u) => u.includes('example.invalid'))).toBe(false)
    window.history.replaceState(null, '', '/')
  })

  it('falls back to /api/report then ./report.json', async () => {
    mockFetchSequence({
      '/api/report': { ok: false, status: 503 },
      './report.json': { ok: true, body: fakeReport },
    })
    await expect(loadReport()).resolves.toEqual(fakeReport)
  })

  it('throws the last candidate error when every source fails', async () => {
    mockFetchSequence({})
    await expect(loadReport()).rejects.toThrow(/report\.json/)
  })
})
