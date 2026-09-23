/**
 * The centre of the application: the network, given the whole middle column.
 *
 * Two rows. The stage holds the map and one overlay, the view switch, parked in
 * empty sky at the top left. Everything else - legend, origin and the playback
 * transport - lives in a docked bar underneath, so no control can cover a
 * station name, a route or another control.
 */

import { useLayoutEffect, useRef, useState } from 'react'

import { LoadingState, ErrorState } from '../common/States.jsx'
import { NetworkMap } from './NetworkMap.jsx'
import './NetworkCanvas.css'

export const VIEWS = [
  { id: 'network', label: 'Network' },
  { id: 'classical', label: 'Classical NN' },
  { id: 'quantum', label: 'Hybrid QAOA' },
  { id: 'compare', label: 'Comparison' },
]

export function NetworkCanvas({
  status,
  stations,
  lines,
  error,
  onRetry,
  view,
  onViewChange,
  disabledViews,
  classicalLegs,
  quantumLegs,
  start,
  onSelectStation,
  locked,
}) {
  const tabsRef = useRef(null)
  const [marker, setMarker] = useState({ x: 0, w: 0 })
  // The map portals its transport into this node, so the controls render
  // inside the docked bar rather than on top of the map.
  const [barNode, setBarNode] = useState(null)

  useLayoutEffect(() => {
    const host = tabsRef.current
    if (!host) return undefined
    const move = () => {
      const on = host.querySelector('[data-on="true"]')
      if (on) setMarker({ x: on.offsetLeft, w: on.offsetWidth })
    }
    move()
    const observer = new ResizeObserver(move)
    observer.observe(host)
    return () => observer.disconnect()
  }, [view])

  const showClassical = view === 'classical' || view === 'compare'
  const showQuantum = view === 'quantum' || view === 'compare'

  return (
    <div className="canvas">
      <div className="canvas__stage">
        {status === 'loading' && (
          <div className="canvas__state">
            <LoadingState message="Reading the transmission network" />
          </div>
        )}

        {status === 'error' && (
          <div className="canvas__state">
            <ErrorState error={error} onRetry={onRetry} />
          </div>
        )}

        {status === 'ready' && (
          <>
            <NetworkMap
              stations={stations}
              lines={lines}
              view={view}
              classicalLegs={classicalLegs}
              quantumLegs={quantumLegs}
              start={start}
              onSelectStation={locked ? undefined : onSelectStation}
              interactive={!locked}
              controlsHost={barNode}
            />

            <div className="canvas__tabs" ref={tabsRef} role="tablist" aria-label="Map view">
              <span
                className="canvas__marker"
                style={{ transform: `translateX(${marker.x}px)`, width: marker.w }}
                aria-hidden="true"
              />
              {VIEWS.map((option) => {
                const off = disabledViews.includes(option.id)
                const on = view === option.id
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    data-on={on}
                    className={`canvas__tab ${on ? 'is-on' : ''}`}
                    disabled={off}
                    title={off ? 'Available once an optimization has run' : undefined}
                    onClick={() => onViewChange(option.id)}
                  >
                    {option.label}
                  </button>
                )
              })}
            </div>

          </>
        )}
      </div>

      <div className="canvas__bar" ref={setBarNode}>
        <div className="canvas__legend">
          {start && (
            <span className="key key--origin" title={start}>
              <span className="key__dot" />
              {start}
            </span>
          )}
          {showClassical && (
            <span className="key">
              <span className="key__line key__line--classical" />
              Classical NN
            </span>
          )}
          {showQuantum && (
            <span className="key">
              <span className="key__line key__line--quantum" />
              Hybrid QAOA
            </span>
          )}
          <span className="key">
            <span className="key__line key__line--net" />
            Transmission line
          </span>
        </div>
      </div>
    </div>
  )
}
