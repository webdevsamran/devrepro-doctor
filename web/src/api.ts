import type { ScanReport } from './types'

/**
 * Data sources, in priority order:
 * 1. ?src=/path/to/report.json — a sanitized JSON export next to the app
 * 2. /api/report — the optional localhost API served by `devrepro serve`
 * 3. ./report.json — a sanitized export dropped beside the built frontend
 */
export async function loadReport(): Promise<ScanReport> {
  const params = new URLSearchParams(window.location.search)
  const src = params.get('src')
  const candidates = [
    ...(src ? [src] : []),
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