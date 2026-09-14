import type { ScanReport } from '../types'

/**
 * Data sources, in priority order:
 * 1. ?src=/path/to/report.json — a sanitized JSON export next to the app
 * 2. /api/report — the optional localhost API served by `devrepro serve`
 * 3. ./report.json — a sanitized export dropped beside the built frontend
 */

import { sourceOverride } from './source'

export async function loadReport(): Promise<ScanReport> {
  // `?src=` is attacker-supplied: it arrives in a link. Confined to this
  // origin before it reaches `fetch`, because the page renders whatever comes
  // back as a reading of the reader's own machine. See `./source.ts`.
  const override = sourceOverride(window.location.search, window.location.href)
  const candidates = [
    ...(override ? [override] : []),
    '/api/report',
    './report.json',
  ]
  let lastError: unknown = null
  for (const url of candidates) {
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
      return (await res.json()) as ScanReport
    } catch (err) {
      lastError = err
    }
  }
  throw lastError instanceof Error ? lastError : new Error('No data source available')
}