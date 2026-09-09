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

/** Mirrors `ReproducibilityPoint` in devrepro/core/models.py. The field names
 *  here were `name`/`why` and never matched the model, so every row rendered
 *  two empty cells. */
export interface ScorePoint {
  criterion: string
  earned: number
  possible: number
  explanation: string
}

/** `percent` is intentionally absent: it is a Python property, and the report
 *  round-trips through a model that forbids extra fields, so it cannot be
 *  serialized. Derive it with `scorePercent()`. */
export interface Score { total: number; possible: number; points: ScorePoint[] }

/** Same rounding as `ReproducibilityScore.percent` in devrepro/core/models.py. */
export function scorePercent(score: Score): number {
  if (!score.possible) return 0
  return Math.round((100 * score.total) / score.possible * 10) / 10
}

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