/**
 * Data loading for wave-11 capability pages.
 * Source priority: ?src= override, then localhost API (`devrepro serve`),
 * then static JSON exports beside the app. When no real source exists the
 * page falls back to an inline fixture that MUST be rendered with a DEMO
 * banner so demo data can never masquerade as a real machine report.
 */

import { useEffect, useState } from 'react'

const API = 'http://127.0.0.1:8642/api'

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

export interface WithDemo<T> {
  data: T | null
  demo: boolean
  error: string
}

/** Try real sources; on failure hand back the labelled demo fixture. */
async function loadOrDemo<T>(paths: string[], demo: T): Promise<WithDemo<T>> {
  try {
    return { data: await loadJson<T>(paths), demo: false, error: '' }
  } catch (err) {
    return { data: demo, demo: true, error: err instanceof Error ? err.message : String(err) }
  }
}

/* ------------------------------------------------------------- types ----- */

export interface ShellStartupReport {
  shell: string
  total_ms: number
  segments: { script: string; ms: number; note?: string }[]
}

export interface ContainersWslReport {
  docker: { server_version?: string; contexts?: string[]; compose?: boolean; buildkit?: boolean; error?: string }
  podman?: { version?: string; docker_compatible?: boolean }
  wsl: { available: boolean; distros: { name: string; state: string; version: number }[]; kernel?: string }
  guidance: string[]
}

export interface GpuAiReport {
  gpus: { name: string; vendor: string; driver?: string; vram_gb?: number }[]
  cuda?: { driver?: string; toolkit?: string; runtime?: string }
  rocm?: { version?: string }
  frameworks: { name: string; version: string; backend: string }[]
  notes: string[]
}

export interface DriftTimelinePoint {
  snapshot_id: string
  created_at: string
  changed: { component: string; from: string | null; to: string | null }[]
}

export interface GeneratedEnvPreview {
  target: string
  path: string
  content: string
  review_required: boolean
}

export interface PluginEntry {
  name: string
  group: string
  version: string
  capabilities: string[]
  network: boolean
  privileged: boolean
}

/* ------------------------------------------------------------ loaders ---- */

const DEMO_SHELL: ShellStartupReport = {
  shell: 'pwsh',
  total_ms: 412,
  segments: [
    { script: 'profile.ps1', ms: 180, note: 'conda hook dominates startup' },
    { script: 'nvm-init', ms: 120 },
    { script: 'completion-cache', ms: 40 },
  ],
}
export const loadShellStartup = () =>
  loadOrDemo<ShellStartupReport>([`${API}/shell-startup`, './shell-startup.json'], DEMO_SHELL)

const DEMO_CONTAINERS: ContainersWslReport = {
  docker: { server_version: '26.1.3', contexts: ['default', 'desktop-linux'], compose: true, buildkit: true },
  podman: { version: '5.1.1', docker_compatible: true },
  wsl: {
    available: true,
    distros: [{ name: 'Ubuntu-24.04', state: 'Running', version: 2 }],
    kernel: '5.15.146',
  },
  guidance: [
    'DEMO DATA — run `devrepro scan` for real values.',
    'Project on /mnt/c: move it into the WSL filesystem for faster builds.',
  ],
}
export const loadContainersWsl = () =>
  loadOrDemo<ContainersWslReport>([`${API}/containers-wsl`, './containers-wsl.json'], DEMO_CONTAINERS)

const DEMO_GPU: GpuAiReport = {
  gpus: [{ name: 'NVIDIA RTX 4070 (DEMO)', vendor: 'nvidia', driver: '550.67', vram_gb: 12 }],
  cuda: { driver: '12.4', toolkit: '12.3', runtime: '12.2' },
  frameworks: [
    { name: 'torch', version: '2.3.1+cu121', backend: 'cuda' },
    { name: 'onnxruntime', version: '1.18.0', backend: 'cpu-only build' },
  ],
  notes: [
    'DEMO DATA — run `devrepro scan` for real values.',
    'onnxruntime was built without CUDA support; install onnxruntime-gpu for GPU inference.',
  ],
}
export const loadGpuAi = () => loadOrDemo<GpuAiReport>([`${API}/gpu-ai`, './gpu-ai.json'], DEMO_GPU)

const DEMO_DRIFT: DriftTimelinePoint[] = [
  {
    snapshot_id: 'snap-demo-a',
    created_at: '2026-08-20T09:00:00Z',
    changed: [{ component: 'node (DEMO)', from: '22.2.0', to: '22.4.0' }],
  },
  {
    snapshot_id: 'snap-demo-b',
    created_at: '2026-08-25T17:30:00Z',
    changed: [
      { component: 'python (DEMO)', from: '3.12.4', to: '3.13.0' },
      { component: 'PATH entry npm-global (DEMO)', from: null, to: 'added' },
    ],
  },
]
export const loadDriftTimeline = () =>
  loadOrDemo<DriftTimelinePoint[]>([`${API}/drift-timeline`, './drift-timeline.json'], DEMO_DRIFT)

const DEMO_GENERATED: GeneratedEnvPreview[] = [
  {
    target: '.devcontainer/devcontainer.json',
    path: '.devcontainer/devcontainer.json',
    review_required: true,
    content:
      '{\n  "name": "generated by devrepro generate",\n  "image": "mcr.microsoft.com/devcontainers/typescript-node:22"\n}\n',
  },
  {
    target: '.tool-versions',
    path: '.tool-versions',
    review_required: true,
    content: '# generated by devrepro generate — REVIEW BEFORE COMMITTING\nnodejs 22.4.0\npython 3.12.4\n',
  },
]
export const loadGeneratedEnv = () =>
  loadOrDemo<GeneratedEnvPreview[]>([`${API}/generated-env`, './generated-env.json'], DEMO_GENERATED)

const DEMO_PLUGINS: PluginEntry[] = [
  { name: 'core-python (DEMO)', group: 'probes', version: '2.0.0', capabilities: ['filesystem.read'], network: false, privileged: false },
  { name: 'registry-probe (DEMO)', group: 'probes', version: '2.0.0', capabilities: ['registry.read'], network: false, privileged: false },
]
export const loadPlugins = () =>
  loadOrDemo<PluginEntry[]>([`${API}/plugins`, './plugins.json'], DEMO_PLUGINS)

/* --------------------------------------------- enterprise (server API) --- */

export interface AuditEvent {
  id: number
  actor: string
  action: string
  target: string
  created_at: string
}
export const loadAuditLog = () =>
  loadOrDemo<AuditEvent[]>(['http://127.0.0.1:8642/fleet/audit', './audit.json'], [
    { id: 1, actor: 'sa:ci-bot (DEMO)', action: 'policy.set', target: 'tool-versions', created_at: '2026-08-25T10:12:00Z' },
    { id: 2, actor: 'machine:ws-114 (DEMO)', action: 'snapshot.publish', target: 'machine/42', created_at: '2026-08-25T10:14:00Z' },
  ])

export interface PolicyException {
  id: number
  policy: string
  justification: string
  expires_at: string
  reviewer: string | null
  approved: boolean
}
export const loadExceptions = () =>
  loadOrDemo<PolicyException[]>(['http://127.0.0.1:8642/fleet/exceptions', './exceptions.json'], [
    {
      id: 7,
      policy: 'prohibited-runtimes/python-3.9 (DEMO)',
      justification: 'legacy billing service until Q4 migration',
      expires_at: '2026-11-01T00:00:00Z',
      reviewer: null,
      approved: false,
    },
  ])

export interface AgentRow {
  machine_key: string
  os_name: string
  arch: string
  last_snapshot: string | null
  readiness: string
}
export const loadAgents = () =>
  loadOrDemo<AgentRow[]>(['http://127.0.0.1:8642/fleet/machines', './agents.json'], [
    { machine_key: 'DEMO-ws-101', os_name: 'windows', arch: 'x86_64', last_snapshot: '2026-08-25T08:00:00Z', readiness: 'READY_WITH_WARNINGS' },
    { machine_key: 'DEMO-mb-14', os_name: 'darwin', arch: 'arm64', last_snapshot: '2026-08-25T09:10:00Z', readiness: 'BLOCKED' },
  ])

export interface RetentionConfig {
  snapshot_days: number
  audit_days: number
}
export const loadRetention = () =>
  loadOrDemo<RetentionConfig>(
    ['http://127.0.0.1:8642/fleet/retention', './retention.json'],
    { snapshot_days: 90, audit_days: 365 },
  )

/** Generic async hook with loading/error states for WithDemo payloads. */
export function useAsync2<T>(fn: () => Promise<WithDemo<T>>): {
  result: WithDemo<T> | null
  error: string | null
} {
  const [result, setResult] = useState<WithDemo<T> | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    fn()
      .then((d) => alive && setResult(d))
      .catch((e) => alive && setError(String(e)))
    return () => {
      alive = false
    }
    // fn is captured once on mount by design
  }, [])
  return { result, error }
}
