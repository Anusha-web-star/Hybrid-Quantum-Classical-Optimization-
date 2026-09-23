/**
 * Choosing the starting station.
 *
 * A searchable listbox over every station the API returned - the list is never
 * hardcoded and never truncated, so all 26 are always reachable. Filtering is
 * presentation only; the backend still resolves the name it is given.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

import './StartStationSelect.css'

export function StartStationSelect({ stations, value, onChange, disabled = false }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return stations
    return stations.filter(
      (station) =>
        station.name.toLowerCase().includes(needle) ||
        station.type?.toLowerCase().includes(needle),
    )
  }, [stations, query])

  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(Math.max(0, stations.findIndex((s) => s.name === value)))
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open, stations, value])

  useEffect(() => {
    if (!open) return
    listRef.current
      ?.querySelector('[data-cursor="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [cursor, open])

  const choose = (name) => {
    onChange(name)
    setOpen(false)
  }

  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(c + 1, filtered.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (event.key === 'Enter' && filtered[cursor]) {
      event.preventDefault()
      choose(filtered[cursor].name)
    }
  }

  const selected = stations.find((station) => station.name === value)

  return (
    <div className="stationselect" ref={rootRef}>
      <button
        type="button"
        className={`stationselect__trigger ${open ? 'is-open' : ''}`}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="stationselect__triggertext">
          {selected ? (
            <>
              <span className="stationselect__name">{selected.name}</span>
              <span className="stationselect__sub mono">
                {selected.connections} line{selected.connections === 1 ? '' : 's'},{' '}
                {selected.latitude?.toFixed(2)}N {selected.longitude?.toFixed(2)}E
              </span>
            </>
          ) : (
            <span className="stationselect__placeholder">Select an origin station</span>
          )}
        </span>
        <span className="stationselect__chevron" aria-hidden="true">
          ▾
        </span>
      </button>

      {open && (
        <div className="stationselect__pop" role="presentation">
          <input
            ref={inputRef}
            className="stationselect__search"
            type="text"
            placeholder={`Search ${stations.length} stations`}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setCursor(0)
            }}
            onKeyDown={onKeyDown}
            aria-label="Search stations"
          />

          <ul className="stationselect__list" ref={listRef} role="listbox" tabIndex={-1}>
            {filtered.length === 0 && (
              <li className="stationselect__none">No station matches that name.</li>
            )}
            {filtered.map((station, index) => {
              const isSelected = station.name === value
              return (
                <li key={station.name}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    data-cursor={index === cursor}
                    className={`stationselect__option ${isSelected ? 'is-selected' : ''} ${
                      index === cursor ? 'is-cursor' : ''
                    }`}
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => choose(station.name)}
                  >
                    <span className="stationselect__optionname">{station.name}</span>
                    <span className="stationselect__optionmeta mono">
                      {station.connections}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>

          <p className="stationselect__foot mono">
            {filtered.length} of {stations.length} stations
          </p>
        </div>
      )}
    </div>
  )
}
