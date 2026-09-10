import { lazy } from 'react'
import type { ComponentType } from 'react'
import type { ScanReport } from './types'

/**
 * Route table: which component renders each nav id, and whether it needs the
 * scan report.
 *
 * Every entry is `lazy`, so the four page modules become four chunks that load
 * on demand. The previous shell imported all of them eagerly and rendered a
 * thirty-two branch `{page === 'x' && <Page/>}` chain, which meant every
 * visitor downloaded every view in order to look at one.
 *
 * The two prop shapes are kept in separate maps rather than unified behind a
 * cast: the router then passes `report` exactly where it is wanted, and
 * TypeScript catches a page moved between the maps.
 */

export type ReportPageProps = { report: ScanReport }
export type ReportPage = ComponentType<ReportPageProps>
export type PlainPage = ComponentType

const core = () => import('./pages/core')
const diff = () => import('./pages/diff')
const environment = () => import('./pages/environment')
const platform = () => import('./pages/platform')
const enterprise = () => import('./pages/enterprise')

function reportPage<M extends Record<string, unknown>>(
  load: () => Promise<M>,
  name: keyof M & string,
): ReportPage {
  return lazy(async () => ({ default: (await load())[name] as ReportPage }))
}

function plainPage<M extends Record<string, unknown>>(
  load: () => Promise<M>,
  name: keyof M & string,
): PlainPage {
  return lazy(async () => ({ default: (await load())[name] as PlainPage }))
}

/** Views that render the scan report. */
export const REPORT_PAGES: Record<string, ReportPage> = {
  overview: reportPage(core, 'OverviewPage'),
  readiness: reportPage(core, 'ReadinessPage'),
  toolchains: reportPage(core, 'ToolchainsPage'),
  path: reportPage(core, 'PathPage'),
  findings: reportPage(core, 'FindingsPage'),
  snapshots: reportPage(core, 'SnapshotsPage'),
  rules: reportPage(core, 'RulesPage'),
  remediation: reportPage(core, 'RemediationPage'),
  about: reportPage(core, 'AboutPage'),
  containers: reportPage(platform, 'ContainersWslPage'),
}

/** Views that fetch their own data or need none. */
export const PLAIN_PAGES: Record<string, PlainPage> = {
  diff: plainPage(diff, 'DiffPage'),
  history: plainPage(core, 'HistoryPage'),
  docs: plainPage(core, 'DocsPage'),
  contributors: plainPage(core, 'ContributorsPage'),

  profile: plainPage(environment, 'ProfilePage'),
  baseline: plainPage(environment, 'BaselinePage'),
  envvars: plainPage(environment, 'EnvVarsPage'),
  services: plainPage(environment, 'ServicesPage'),
  githealth: plainPage(environment, 'GitHealthPage'),
  network: plainPage(environment, 'NetworkTlsPage'),
  fleet: plainPage(environment, 'FleetDashboardPage'),

  gpustack: plainPage(platform, 'GpuAiStackPage'),
  shellstartup: plainPage(platform, 'ShellStartupPage'),
  drifttimeline: plainPage(platform, 'DriftTimelinePage'),
  generatedenv: plainPage(platform, 'GeneratedEnvPage'),
  plugins: plainPage(platform, 'PluginCatalogPage'),

  agents: plainPage(enterprise, 'AgentsEnrollmentPage'),
  exceptions: plainPage(enterprise, 'ExceptionsPage'),
  auditlog: plainPage(enterprise, 'AuditLogPage'),
  retention: plainPage(enterprise, 'RetentionPage'),
  serversettings: plainPage(enterprise, 'ServerSettingsPage'),
}

export type HomePageProps = { onStart: () => void }
export const HomePage: ComponentType<HomePageProps> = lazy(async () => ({
  default: (await core()).HomePage as ComponentType<HomePageProps>,
}))
