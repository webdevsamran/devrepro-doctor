import { Suspense, useCallback, useEffect, useState } from 'react'
import {
  HashRouter,
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import { loadReport } from './api/report'
import { CommandPalette, usePaletteShortcut } from './components/CommandPalette'
import { ErrorState, Loading, RouteSkeleton } from './components/ui'
import { useTheme } from './hooks/useTheme'
import { GROUP_OF, NAV_GROUPS, itemById } from './nav'
import { HomePage, PLAIN_PAGES, REPORT_PAGES } from './routes'
import type { ScanReport } from './types'

/**
 * Hash routing, deliberately.
 *
 * The built console is served three ways: by `devrepro serve`, from a static
 * directory, and by opening the built index.html straight off disk. Only hash
 * URLs work in all three, and losing the third would remove the zero-setup
 * path for someone who has been handed a report and a folder.
 */
export default function App() {
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  )
}

const SIDEBAR_KEY = 'devrepro:sidebar'

function Shell() {
  const [report, setReport] = useState<ScanReport | null>(null)
  const [error, setError] = useState('')
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === 'collapsed'
    } catch {
      return false
    }
  })
  const { theme, cycle } = useTheme()
  const location = useLocation()

  usePaletteShortcut(useCallback(() => setPaletteOpen(true), []))

  useEffect(() => {
    loadReport()
      .then(setReport)
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? 'collapsed' : 'expanded')
    } catch {
      /* a layout preference is not worth an exception */
    }
  }, [collapsed])

  // Close the mobile sheet on navigation, or it covers the page just opened.
  useEffect(() => setSheetOpen(false), [location.pathname])

  const current = itemById(location.pathname.replace(/^\//, '')) ?? itemById('home')

  return (
    <div className="app" data-sidebar={collapsed ? 'collapsed' : 'expanded'}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      <aside className="sidebar" data-open={sheetOpen} aria-label="Sections">
        {/* The label is explicit because `.brand-text` is hidden below 68rem
            and the mark is decorative, which left the link with no accessible
            name at all on tablet and phone widths. */}
        <Link to="/home" className="brand" aria-label="DevRepro Doctor, home">
          <span className="brand-mark" aria-hidden="true">
            ◉
          </span>
          <span className="brand-text">DevRepro Doctor</span>
        </Link>
        <nav className="nav">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="nav-group-title">{group.title}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.id}
                  to={'/' + item.id}
                  className="nav-link"
                  title={item.label}
                >
                  <span className="nav-icon" aria-hidden="true">
                    {item.icon}
                  </span>
                  <span className="sidebar-label">{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <header className="topbar">
        <button
          className="btn btn-ghost btn-icon"
          onClick={() => {
            setCollapsed((c) => !c)
            setSheetOpen((s) => !s)
          }}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          ☰
        </button>

        <nav aria-label="Breadcrumb" className="small muted truncate">
          {current && GROUP_OF[current.id] !== current.label && (
            <>
              <span>{GROUP_OF[current.id]}</span>
              <span aria-hidden="true"> / </span>
            </>
          )}
          <strong style={{ color: 'var(--fg)' }}>{current?.label ?? 'Home'}</strong>
        </nav>

        <div className="spacer" />

        <button
          className="btn btn-sm"
          onClick={() => setPaletteOpen(true)}
          aria-label="Open command palette"
        >
          <span aria-hidden="true">⌕</span>
          <span className="sidebar-label">Jump to…</span>
          <kbd>⌘K</kbd>
        </button>

        <button
          className="btn btn-ghost btn-icon"
          onClick={cycle}
          aria-label={`Theme: ${theme}. Click to change.`}
          title={`Theme: ${theme}`}
        >
          {theme === 'system' ? '◐' : theme === 'light' ? '☀' : '☾'}
        </button>
      </header>

      <main id="main" className="content" tabIndex={-1}>
        {error ? (
          <ErrorState message={error} />
        ) : (
          <Suspense fallback={<RouteSkeleton />}>
            <Routes>
              <Route path="/" element={<Navigate to="/home" replace />} />
              <Route path="/home" element={<HomeRoute />} />
              {Object.entries(REPORT_PAGES).map(([id, Page]) => (
                <Route
                  key={id}
                  path={'/' + id}
                  element={report ? <Page report={report} /> : <Loading />}
                />
              ))}
              {Object.entries(PLAIN_PAGES).map(([id, Page]) => (
                <Route key={id} path={'/' + id} element={<Page />} />
              ))}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        )}
      </main>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}

function HomeRoute() {
  const navigate = useNavigate()
  return <HomePage onStart={() => navigate('/overview')} />
}

function NotFound() {
  return (
    <div className="state">
      <div className="state-icon" aria-hidden="true">
        ⌕
      </div>
      <h2>No such view</h2>
      <p className="muted">
        That address does not match any section of the console.
      </p>
      <Link className="btn btn-primary" to="/home">
        Back to Home
      </Link>
    </div>
  )
}
