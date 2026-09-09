import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'

const KEY = 'devrepro:theme'

/**
 * Theme with three states and persistence.
 *
 * The previous toggle was a boolean in component state: it could not express
 * "follow the system", and it forgot the choice on every reload. `system` is
 * the default and stamps no attribute, so the CSS media query decides; an
 * explicit choice stamps `data-theme` and wins in both directions.
 *
 * localStorage can throw outright in a private window or with site data
 * blocked, so every access is guarded. A theme preference is not worth an
 * exception.
 */
export function useTheme(): {
  theme: Theme
  resolved: 'light' | 'dark'
  setTheme: (t: Theme) => void
  cycle: () => void
} {
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      const stored = localStorage.getItem(KEY)
      if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
    } catch {
      /* storage unavailable; fall through to the system default */
    }
    return 'system'
  })

  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  )

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      /* preference is not worth an exception */
    }
  }, [theme])

  const setTheme = useCallback((t: Theme) => setThemeState(t), [])
  const cycle = useCallback(
    () => setThemeState((t) => (t === 'system' ? 'light' : t === 'light' ? 'dark' : 'system')),
    [],
  )

  const resolved: 'light' | 'dark' =
    theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  return { theme, resolved, setTheme, cycle }
}
