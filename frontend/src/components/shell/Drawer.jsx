/**
 * The secondary surface.
 *
 * Routes, energy, figures, methodology and the project assistant all matter,
 * but none of them belong in the first view. Collapsed, the drawer is a 40px tab strip; opened, it
 * takes the lower half of the panel and the canvas keeps running behind it.
 *
 * This is where the long-form content went. The old build put the methodology
 * at the top of the page and pushed the controls below the fold.
 */

import { useEffect } from 'react'
import { CaretDown } from '@phosphor-icons/react'

import './Drawer.css'

export const TABS = [
  { id: 'routes', label: 'Routes' },
  { id: 'energy', label: 'Energy loss' },
  { id: 'figures', label: 'Figures' },
  { id: 'method', label: 'Method' },
  { id: 'assistant', label: 'Assistant' },
]

export function Drawer({ open, tab, onTabChange, onToggle, badge, children }) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => event.key === 'Escape' && onToggle(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onToggle])

  return (
    <section className={`drawer ${open ? 'is-open' : ''}`}>
      <div className="drawer__strip">
        <div className="drawer__tabs" role="tablist" aria-label="Detail panels">
          {TABS.map((entry) => {
            const on = open && tab === entry.id
            return (
              <button
                key={entry.id}
                type="button"
                role="tab"
                aria-selected={on}
                className={`drawer__tab ${on ? 'is-on' : ''}`}
                onClick={() => {
                  if (open && tab === entry.id) onToggle(false)
                  else {
                    onTabChange(entry.id)
                    onToggle(true)
                  }
                }}
              >
                {entry.label}
                {entry.id === 'routes' && badge && (
                  <span className="drawer__badge mono">{badge}</span>
                )}
              </button>
            )
          })}
        </div>

        <button
          type="button"
          className="drawer__toggle"
          onClick={() => onToggle(!open)}
          aria-expanded={open}
        >
          <CaretDown size={13} weight="bold" className="drawer__caret" />
          <span>{open ? 'Collapse' : 'Expand'}</span>
        </button>
      </div>

      <div className="drawer__body scroll-y" hidden={!open}>
        {children}
      </div>
    </section>
  )
}

/** A collapsible block, used for the technical explanation inside Method. */
export function Disclosure({ summary, children, defaultOpen = false }) {
  return (
    <details className="disc" open={defaultOpen}>
      <summary className="disc__summary">
        <CaretDown size={12} weight="bold" className="disc__caret" />
        {summary}
      </summary>
      <div className="disc__body">{children}</div>
    </details>
  )
}
