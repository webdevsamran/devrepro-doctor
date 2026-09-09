import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { GROUP_OF, searchItems } from '../nav'

/**
 * Jump-to-anywhere, on ⌘K / Ctrl-K.
 *
 * With thirty-odd views, the fastest route to one of them is typing its name.
 * The palette is the reason the sidebar can afford to collapse: navigation
 * stops depending on every destination being visible at once.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const navigate = useNavigate()

  const results = searchItems(query)

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      // Focus after paint, or the input is not yet in the document.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // Keep the highlighted row in view when arrowing past the fold. Guarded
  // because `scrollIntoView` is not universally implemented -- jsdom omits it,
  // and so do some embedded webviews. Scrolling is a nicety; throwing here
  // would take the whole palette down with it.
  useEffect(() => {
    const row = listRef.current?.querySelector('[aria-selected="true"]')
    if (row instanceof HTMLElement && typeof row.scrollIntoView === 'function') {
      row.scrollIntoView({ block: 'nearest' })
    }
  }, [active])

  const go = useCallback(
    (id: string) => {
      navigate('/' + id)
      onClose()
    },
    [navigate, onClose],
  )

  if (!open) return null

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = results[active]
      if (item) go(item.id)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  return (
    <div
      className="palette-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onKeyDown={onKeyDown}
      >
        <input
          ref={inputRef}
          /* autoFocus as well as the rAF call above: the effect covers a
             re-open, this covers the first mount, and neither is reliable
             alone across browsers. */
          autoFocus
          className="palette-input"
          placeholder="Jump to a view…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={results[active] ? `palette-${results[active].id}` : undefined}
          autoComplete="off"
          spellCheck={false}
        />
        {results.length === 0 ? (
          <p className="palette-empty">No view matches “{query}”.</p>
        ) : (
          <ul className="palette-list" id="palette-list" role="listbox" ref={listRef}>
            {results.map((item, i) => (
              <li
                key={item.id}
                id={`palette-${item.id}`}
                className="palette-item"
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault()
                  go(item.id)
                }}
              >
                <span aria-hidden="true">{item.icon}</span>
                <span>{item.label}</span>
                <span className="palette-group">{GROUP_OF[item.id]}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/** Wire ⌘K / Ctrl-K, ignoring the shortcut while the user is typing elsewhere. */
export function usePaletteShortcut(onOpen: () => void): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        onOpen()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onOpen])
}
