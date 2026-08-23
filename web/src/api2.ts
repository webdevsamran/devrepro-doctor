/**
 * Data loading for wave-3/4/7 capability pages.
 * Same source-priority model as api.ts: ?src= override, then the localhost
 * API served by `devrepro serve`, then static JSON exports beside the app.
 */

async function loadJson<T>(paths: string[]): Promise<T> {
  const params = new URLSearchParams(window.location.search)
  const src = params.get('src')
  const candidates = [...(src ? [src.replace(/report\.json$/, '')] : []), ...paths]
  let lastError: unknown = null
  for (const url of candidates) {
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
      return (await res.json()) as T
    } catch (err) {
      lastError = err
    }
  }
  throw lastError instanceof Error ? lastError : new Error('No data source available')
}

export interface ProfilePayload {
  profile: string
  confidence: number
  signals: string[]
  maturity: {
    total: number
    possible: number
    percent: number
    factors: { name: string; earned: number; weight: number; detail: string }[]
    explanation: string
  }
}

export interface BaselineDiffEntry {
  component: string
  name: string
  severity: 'ok' | 'warn' | 'blocker'
  project_impact: string
  expected: string
  actual: string
}

export interface EnvReport {
  origins: { name: string; source: string; kind: string; has_value: boolean }[]
  missing_required: string[]
  forbidden_present: string[]
  duplicated: Record<string, string[]>
  dotenv_findings: { path: string; severity: string; detail: string }[]
  ok: boolean
}

export interface PortsReport {
  declared_ports: { port: number; source: string; service: string }[]
  conflicts: { port: number; free: boolean; service: string }[]
  inferred_services: Record<string, { host: string; port: number }>
  probes?: { service: string; host: string; port: number; reachable: boolean; detail: string }[]
}

export interface GitHealth {
  is_repo: boolean
  linked_worktree: boolean
  config: Record<string, string>
  signing_configured: boolean
  credential_helper_present: boolean
  lfs_available: boolean
  submodules: { path: string; initialized: boolean; dirty: boolean }[]
  notes: string[]
}

export interface NetworkReport {
  network_checks_opt_in: boolean
  proxy: { env: Record<string, string>; git_proxy: string | null }
  clock: { utc_now: string; skew_seconds: number; plausible: boolean; detail: string }
  tls?: { host: string; ok: boolean; classification: string; detail: string }[] | null
  registries?: { name: string; reachable: boolean; detail: string }[]
}

export interface FleetMachine {
  machine_key: string
  os_name: string
  arch: string
  label?: string
  project?: string | null
  verdict?: string
  tools?: Record<string, string>
}

export interface FleetDashboard {
  machines: FleetMachine[]
  readiness_distribution: Record<string, number>
  segmentation: { os: string; arch: string; verdict: string; machines: number }[]
  heatmap: Record<string, Record<string, number>>
  compliance?: { machine_key: string; compliant: boolean; failures: { tool: string; expected: string; actual: string }[] }[]
}

const API = '/api'

export const loadProfile = () => loadJson<ProfilePayload>([`${API}/profile`, './profile.json'])
export const loadBaseline = () =>
  loadJson<{ baseline_id: string; entries: BaselineDiffEntry[] }>([`${API}/baseline-diff`, './baseline-diff.json'])
export const loadEnv = () => loadJson<EnvReport>([`${API}/env`, './env.json'])
export const loadPorts = () => loadJson<PortsReport>([`${API}/ports`, './ports.json'])
export const loadGitHealth = () => loadJson<GitHealth>([`${API}/git-health`, './git-health.json'])
export const loadNetwork = () => loadJson<NetworkReport>([`${API}/network`, './network.json'])
export const loadFleet = () => loadJson<FleetDashboard>([`${API}/fleet`, './fleet.json'])

/** Generic async-data hook with loading/error states. */
import { useEffect, useState } from 'react'

export function useAsync<T>(fn: () => Promise<T>): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    fn()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)))
    return () => {
      alive = false
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- fn is captured once on mount by design
  }, [])
  return { data, error }
}