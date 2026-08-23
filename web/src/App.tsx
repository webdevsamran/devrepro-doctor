import { useEffect, useState } from 'react'
import { loadReport } from './api'
import type { ScanReport } from './types'
import { ErrorState, Loading } from './components'
import {
  AboutPage, ContributorsPage, DiffPage, DocsPage, FindingsPage, HistoryPage,
  HomePage, OverviewPage, PathPage, ReadinessPage, RemediationPage, RulesPage,
  SnapshotsPage, ToolchainsPage,
} from './pages'
import {
  BaselinePage, EnvVarsPage, FleetDashboardPage, GitHealthPage,
  NetworkTlsPage, ProfilePage, ServicesPage,
} from './pages2'

const NAV = [
  ['home', 'Home'],
  ['overview', 'Machine Overview'],
  ['readiness', 'Project Readiness'],
  ['profile', 'Profile & Maturity'],
  ['baseline', 'Baseline'],
  ['toolchains', 'Toolchains'],
  ['path', 'PATH Explorer'],
  ['envvars', 'Env Vars'],
  ['services', 'Ports & Services'],
  ['githealth', 'Git Health'],
  ['network', 'Network & TLS'],
  ['findings', 'Findings'],
  ['diff', 'Environment Diff'],
  ['snapshots', 'Snapshots'],
  ['rules', 'Rules'],
  ['remediation', 'Remediation Plan'],
  ['history', 'History'],
  ['fleet', 'Fleet Dashboard'],
  ['docs', 'Docs'],
  ['contributors', 'Contributors'],
  ['about', 'About'],
] as const

type PageId = (typeof NAV)[number][0]

export default function App() {
  const [report, setReport] = useState<ScanReport | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState<PageId>('home')
  const [dark, setDark] = useState(() =>
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true)

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [dark])

  useEffect(() => {
    loadReport().then(setReport).catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    const onHash = () => setPage(((window.location.hash.slice(1) || 'home') as PageId))
    window.addEventListener('hashchange', onHash)
    onHash()
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const navigate = (id: PageId) => {
    window.location.hash = id
    setPage(id)
  }

  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="topbar">
        <button className="brand" onClick={() => navigate('home')}>🩺 DevRepro Doctor</button>
        <nav aria-label="Main navigation" className="nav">
          {NAV.map(([id, label]) => (
            <a key={id} href={`#${id}`} className={page === id ? 'nav-link active' : 'nav-link'}
               aria-current={page === id ? 'page' : undefined}>
              {label}
            </a>
          ))}
        </nav>
        <button className="btn btn-small" onClick={() => setDark(!dark)} aria-label="Toggle dark mode">
          {dark ? '☀️ Light' : '🌙 Dark'}
        </button>
      </header>
      <main id="main" className="content">
        {error ? <ErrorState message={error} /> :
         !report ? <Loading /> : (
          <>
            {page === 'home' && <HomePage onStart={() => navigate('overview')} />}
            {page === 'overview' && <OverviewPage report={report} />}
            {page === 'readiness' && <ReadinessPage report={report} />}
            {page === 'profile' && <ProfilePage />}
            {page === 'baseline' && <BaselinePage />}
            {page === 'toolchains' && <ToolchainsPage report={report} />}
            {page === 'path' && <PathPage report={report} />}
            {page === 'envvars' && <EnvVarsPage />}
            {page === 'services' && <ServicesPage />}
            {page === 'githealth' && <GitHealthPage />}
            {page === 'network' && <NetworkTlsPage />}
            {page === 'findings' && <FindingsPage report={report} />}
            {page === 'diff' && <DiffPage />}
            {page === 'snapshots' && <SnapshotsPage report={report} />}
            {page === 'rules' && <RulesPage report={report} />}
            {page === 'remediation' && <RemediationPage report={report} />}
            {page === 'history' && <HistoryPage />}
            {page === 'fleet' && <FleetDashboardPage />}
            {page === 'docs' && <DocsPage />}
            {page === 'contributors' && <ContributorsPage />}
            {page === 'about' && <AboutPage report={report} />}
          </>
        )}
      </main>
      <footer className="footer">
        <span>Read-only diagnostics · Privacy-redacted · No telemetry</span>
        <span>Created by @webdevsamran · Apache-2.0</span>
      </footer>
    </div>
  )
}