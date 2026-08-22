export type FindingState = 'PASS' | 'INFO' | 'WARN' | 'ERROR' | 'BLOCKED' | 'UNKNOWN'

export interface Evidence {
  source: string
  command?: string[]
  path?: string
  excerpt?: string
}

export interface Finding {
  rule_id: string
  state: FindingState
  summary: string
  detected?: string
  required?: string
  component?: string
  remediation_hint?: string
  references?: string[]
  evidence: Evidence[]
}

export interface ToolInstallation {
  name: string
  version?: string
  exe_path?: string
  install_source?: string
  is_active?: boolean
}

export interface PathEntry {
  raw: string
  normalized: string
  exists: boolean
  origin: string
  index: number
}

export interface PathAnalysis {
  entries: PathEntry[]
  duplicates: string[]
  dead_entries: string[]
  shadowed_executables: [string, string, string][]
  store_aliases: string[]
  tool_manager_interference: string[]
}

export interface ProjectRequirement {
  ecosystem: string
  name: string
  spec: string
  kind: string
  source_file: string
  optional?: boolean
  note?: string
}

export interface ScorePoint { name: string; earned: number; possible: number; why: string }

export interface Score { total: number; possible: number; percent: number; points: ScorePoint[] }

export interface ScanReport {
  schema_version: string
  devrepro_version: string
  created_at: string
  platform: { os_name: string; os_version: string; arch: string; kernel?: string }
  findings: Finding[]
  tools: ToolInstallation[]
  path_analysis?: PathAnalysis
  requirements: ProjectRequirement[]
  score?: Score
  probe_errors: string[]
  privacy: Record<string, unknown>
}

export interface DiffEntry {
  component: string
  name: string
  classification: string
  a_value?: string
  b_value?: string
  detail?: string
  project_critical: boolean
}

export interface EnvironmentDiff {
  a_snapshot_id: string
  b_snapshot_id: string
  entries: DiffEntry[]
}