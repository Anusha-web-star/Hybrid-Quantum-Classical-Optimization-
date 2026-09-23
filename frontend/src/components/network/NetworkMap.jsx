/**
 * The Karnataka transmission network, drawn from the dataset's own coordinates.
 *
 * Four views over one picture, so the eye never has to re-learn the map:
 *
 *   network     - all 26 stations and 38 transmission lines
 *   classical   - the Nearest Neighbour tour drawn over the faded network
 *   quantum     - the hybrid QAOA tour, same treatment
 *   compare     - both tours together: the classical tour widened into a pale
 *                 halo with the amber quantum line cored inside it, so shared
 *                 segments and divergences are both visible
 *
 * Several stations sit within a few kilometres of each other and collide at map
 * scale. `lib/layout.js` resolves that in the rendering layer only: nodes are
 * nudged the minimum distance needed to separate, each keeping a faint tether
 * to its true projected position, and labels are placed by collision search.
 * Coordinates, distances and topology are untouched, and every line and route
 * is drawn between the same displaced nodes, so the topology stays visually
 * correct.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { createProjection, routeGeometry } from '../../lib/geo.js'
import { useRoutePlayback } from '../../hooks/useRoutePlayback.js'
import { PlaybackControls } from './PlaybackControls.jsx'
import { declutter, placeLabels } from '../../lib/layout.js'
import './NetworkMap.css'

const VIEW_W = 1000
const MIN_ASPECT = 0.55
const MAX_ASPECT = 1.5

export function NetworkMap({
  stations,
  lines,
  view = 'network',
  classicalLegs,
  quantumLegs,
  start,
  onSelectStation,
  interactive = true,
  controlsHost,
}) {
  const [hovered, setHovered] = useState(null)
  const [focus, setFocus] = useState(null)
  const hostRef = useRef(null)
  const [box, setBox] = useState({ width: 1000, height: 680 })

  /*
   * The SVG scales with its container, so a fixed size in viewBox units shrinks
   * on a narrow screen. Tracking the rendered width keeps labels at a roughly
   * constant physical size, and lets the placement pass fit fewer of them when
   * there is genuinely no room.
   */
  useLayoutEffect(() => {
    const host = hostRef.current
    if (!host) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setBox({ width, height })
    })
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  /*
   * The viewBox takes the container's shape so the projection can fill it.
   * Clamped, so an extreme container never squeezes the map into a sliver.
   */
  const viewBox = useMemo(() => {
    const aspect = Math.min(Math.max(box.height / box.width, MIN_ASPECT), MAX_ASPECT)
    return { width: VIEW_W, height: Math.round(VIEW_W * aspect) }
  }, [box])

  const degrees = useMemo(
    () => new Map(stations.map((station) => [station.name, station.connections ?? 0])),
    [stations],
  )

  const radiusOf = useCallback(
    (name) => 4.2 + Math.min(degrees.get(name) ?? 1, 6) * 0.62,
    [degrees],
  )

  // --- geography, then decluttering -------------------------------------
  const { nodes, points } = useMemo(() => {
    const projection = createProjection(stations, {
      width: viewBox.width,
      height: viewBox.height,
      padding: 58,
    })

    const projected = stations
      .map((station) => {
        const point = projection.project(station)
        return point ? { name: station.name, station, x: point.x, y: point.y } : null
      })
      .filter(Boolean)

    const spread = declutter(projected, { minSeparation: 27, maxShift: 30 })
    const index = new Map(spread.map((node) => [node.name, { x: node.x, y: node.y }]))
    return { nodes: spread, points: index }
  }, [stations, viewBox])

  // --- labels -------------------------------------------------------------
  const scale = viewBox.width / Math.max(box.width, 1)
  const fontSize = Math.min(Math.max(10.5 * scale, 10.5), 20)

  const labels = useMemo(
    () =>
      placeLabels(nodes, {
        fontSize,
        bounds: viewBox,
        radiusOf: (node) => radiusOf(node.name),
        text: (node) => shortName(node.name),
        // The origin is labelled first, then the busiest stations.
        priority: (node) => (node.name === start ? 1000 : 0) + (degrees.get(node.name) ?? 0),
      }),
    [nodes, fontSize, radiusOf, degrees, start, viewBox],
  )

  const classicalGeo = useMemo(
    () => routeGeometry(classicalLegs, points),
    [classicalLegs, points],
  )
  const quantumGeo = useMemo(() => routeGeometry(quantumLegs, points), [quantumLegs, points])

  const showClassical = view === 'classical' || view === 'compare'
  const showQuantum = view === 'quantum' || view === 'compare'
  const routeActive = showClassical || showQuantum

  // --- playback ----------------------------------------------------------
  const classicalRef = useRef(null)
  const quantumRef = useRef(null)
  const classicalHeadRef = useRef(null)
  const quantumHeadRef = useRef(null)

  const reducedMotion = usePrefersReducedMotion()

  // Both tours have one leg per station, so in the comparison view they play in
  // lockstep and the divergences show themselves.
  const legCount = showQuantum
    ? (quantumGeo?.legCount ?? 0)
    : showClassical
      ? (classicalGeo?.legCount ?? 0)
      : 0

  /*
   * Called every animation frame. It writes two attributes per visible route
   * and moves the head marker; it deliberately does not touch React state.
   */
  const paint = useCallback(
    ({ leg, progress }) => {
      const step = (pathEl, headEl, geo) => {
        if (!pathEl || !geo) return
        const from = leg <= 0 ? 0 : geo.legEnds[leg - 1]
        const to = geo.legEnds[Math.max(leg, 0)]
        const travelled = leg < 0 ? 0 : from + (to - from) * progress

        pathEl.style.strokeDasharray = `${geo.total} ${geo.total}`
        pathEl.style.strokeDashoffset = `${geo.total - travelled}`

        if (headEl) {
          if (travelled <= 0) {
            headEl.style.opacity = '0'
          } else {
            const point = pathEl.getPointAtLength(travelled)
            headEl.setAttribute('transform', `translate(${point.x} ${point.y})`)
            headEl.style.opacity = '1'
          }
        }
      }

      if (showClassical) step(classicalRef.current, classicalHeadRef.current, classicalGeo)
      if (showQuantum) step(quantumRef.current, quantumHeadRef.current, quantumGeo)
    },
    [showClassical, showQuantum, classicalGeo, quantumGeo],
  )

  const playback = useRoutePlayback({
    legCount,
    // Restarting on any of these means switching view or re-running never
    // leaves the previous route's animation running.
    routeKey: `${view}|${classicalGeo?.d?.length ?? 0}|${quantumGeo?.d?.length ?? 0}`,
    onFrame: paint,
    reducedMotion,
  })

  /* The station the tour is arriving at right now, and those already visited. */
  const activeLegs = showQuantum ? quantumLegs : classicalLegs
  const currentStation =
    playback.legIndex >= 0 ? activeLegs?.[playback.legIndex]?.destination : null
  const visited = useMemo(() => {
    if (!activeLegs || playback.legIndex < 0) return new Set(start ? [start] : [])
    const seen = new Set(start ? [start] : [])
    for (let i = 0; i < playback.legIndex; i += 1) seen.add(activeLegs[i].destination)
    return seen
  }, [activeLegs, playback.legIndex, start])

  useEffect(() => {
    setFocus(null)
  }, [view])

  const active = hovered ?? focus
  const activeNode = active ? nodes.find((node) => node.name === active) : null

  return (
    <div className="netmap" ref={hostRef}>
      <svg
        className="netmap__svg"
        viewBox={`0 0 ${viewBox.width} ${viewBox.height}`}
        role="img"
        aria-label={`Karnataka transmission network: ${stations.length} stations, ${lines.length} transmission lines`}
        onMouseLeave={() => setHovered(null)}
      >
        <defs>
          <pattern id="netgrid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M40 0H0V40" fill="none" stroke="rgba(227,164,79,0.045)" strokeWidth="1" />
          </pattern>
        </defs>

        <rect width={viewBox.width} height={viewBox.height} fill="url(#netgrid)" />

        {/* --- tethers: where a nudged node actually sits ------------------ */}
        <g className="netmap__tethers">
          {nodes
            .filter((node) => node.shift > 4)
            .map((node) => (
              <g key={`t-${node.name}`}>
                <line
                  className="netmap__tether"
                  x1={node.trueX}
                  y1={node.trueY}
                  x2={node.x}
                  y2={node.y}
                />
                <circle className="netmap__anchor" cx={node.trueX} cy={node.trueY} r="1.3" />
              </g>
            ))}
        </g>

        {/* --- transmission lines ----------------------------------------- */}
        <g className={`netmap__lines ${routeActive ? 'is-muted' : ''}`}>
          {lines.map((line) => {
            const a = points.get(line.source)
            const b = points.get(line.destination)
            if (!a || !b) return null
            const touched = active === line.source || active === line.destination
            return (
              <line
                key={`${line.source}|${line.destination}`}
                className={`netmap__line ${touched ? 'is-active' : ''}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
              >
                <title>
                  {line.source} to {line.destination}, {line.distance_km.toFixed(3)} km
                  {line.voltage_kv ? `, ${line.voltage_kv} kV` : ''}
                </title>
              </line>
            )
          })}
        </g>

        {/* --- tours, drawn progressively by the playback clock ------------- */}
        {showClassical && classicalGeo && (
          <RoutePath
            geo={classicalGeo}
            variant="classical"
            overlaid={view === 'compare'}
            pathRef={classicalRef}
            headRef={classicalHeadRef}
          />
        )}
        {showQuantum && quantumGeo && (
          <RoutePath
            geo={quantumGeo}
            variant="quantum"
            pathRef={quantumRef}
            headRef={quantumHeadRef}
          />
        )}

        {/* --- labels, placed by collision search --------------------------- */}
        <g className="netmap__labels">
          {nodes.map((node) => {
            const label = labels.get(node.name)
            if (!label) return null
            const isStart = node.name === start
            const isActive = active === node.name
            return (
              <g key={`l-${node.name}`}>
                {label.leader && (
                  <line
                    className="netmap__leader"
                    x1={node.x}
                    y1={node.y}
                    x2={label.x}
                    y2={label.y}
                  />
                )}
                <text
                  className={`netmap__label ${isStart ? 'is-start' : ''} ${
                    isActive ? 'is-active' : ''
                  }`}
                  x={label.x}
                  y={label.y}
                  style={{ fontSize }}
                  textAnchor={label.anchor}
                  dominantBaseline={label.baseline}
                >
                  {shortName(node.name)}
                </text>
              </g>
            )
          })}
        </g>

        {/* --- stations ------------------------------------------------------ */}
        <g className="netmap__nodes">
          {nodes.map((node) => {
            const isStart = node.name === start
            const isActive = active === node.name
            const radius = radiusOf(node.name)

            return (
              <g
                key={node.name}
                className={`netmap__node ${isStart ? 'is-start' : ''} ${
                  isActive ? 'is-active' : ''
                } ${routeActive && visited.has(node.name) ? 'is-visited' : ''} ${
                  node.name === currentStation ? 'is-current' : ''
                }`}
                transform={`translate(${node.x} ${node.y})`}
                onMouseEnter={() => setHovered(node.name)}
                // Without this, moving off a node but staying inside the map
                // left the readout stuck on the station just left behind.
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setFocus(node.name)}
                onBlur={() => setFocus(null)}
                onClick={() => interactive && onSelectStation?.(node.name)}
                tabIndex={interactive ? 0 : -1}
                role={interactive ? 'button' : undefined}
                aria-label={`${node.name}${isStart ? ' (origin station)' : ''}`}
              >
                {isStart && <circle className="netmap__startring" r={radius + 4.5} />}
                {node.name === currentStation && (
                  <circle className="netmap__currentring" r={radius + 7} />
                )}
                <circle className="netmap__hit" r={Math.max(radius + 9, 13)} />
                <circle className="netmap__dot" r={radius} />
              </g>
            )
          })}
        </g>

        {/* --- hover readout -------------------------------------------------- */}
        {activeNode && (
          <StationCallout
            node={activeNode}
            degree={degrees.get(activeNode.name)}
            isStart={activeNode.name === start}
            scale={scale}
            viewBox={viewBox}
          />
        )}
      </svg>

      {/*
        * Rendered into the canvas's docked bar rather than over the map, so the
        * transport can never sit on top of a station, a label or the legend.
        */}
      {routeActive &&
        legCount > 0 &&
        controlsHost &&
        createPortal(
          <PlaybackControls
            playback={playback}
            reducedMotion={reducedMotion}
            currentStation={currentStation}
            start={start}
          />,
          controlsHost,
        )}
    </div>
  )
}

/** Tracks the user's reduced-motion preference, live. */
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!query) return undefined
    const sync = () => setReduced(query.matches)
    sync()
    query.addEventListener?.('change', sync)
    return () => query.removeEventListener?.('change', sync)
  }, [])
  return reduced
}

/**
 * One tour.
 *
 * The full route is drawn faintly so the shape ahead stays visible, and the
 * travelled portion is revealed over it by the playback clock, which writes the
 * dash offset directly. A head marker rides the front of the line.
 */
function RoutePath({ geo, variant, overlaid = false, pathRef, headRef }) {
  return (
    <g className={`netmap__route netmap__route--${variant} ${overlaid ? 'is-overlaid' : ''}`}>
      <path className="netmap__routeahead" d={geo.d} />
      <path
        ref={pathRef}
        className="netmap__routeline"
        d={geo.d}
        style={{
          strokeDasharray: `${geo.total} ${geo.total}`,
          strokeDashoffset: geo.total,
        }}
      />
      <g ref={headRef} className="netmap__head" style={{ opacity: 0 }}>
        <circle className="netmap__headhalo" r="7" />
        <circle className="netmap__headdot" r="3.2" />
      </g>
    </g>
  )
}

/** Full name and the facts that matter, on hover or keyboard focus. */
function StationCallout({ node, degree, isStart, scale, viewBox }) {
  const size = Math.min(Math.max(11 * scale, 11), 19)
  const pad = 11
  const lineHeight = size * 1.45

  const rows = [
    `${node.station.type}, ${degree ?? 0} line${degree === 1 ? '' : 's'}`,
    `${node.station.latitude?.toFixed(4)}N  ${node.station.longitude?.toFixed(4)}E`,
  ]
  if (isStart) rows.push('origin station')

  const width =
    Math.max(node.name.length * size * 0.55, ...rows.map((row) => row.length * size * 0.53)) +
    pad * 2
  const height = pad * 2 + size * 1.2 + rows.length * lineHeight

  const flipX = node.x + width + 24 > viewBox.width
  const flipY = node.y - height - 18 < 0
  const x = flipX ? node.x - width - 14 : node.x + 14
  const y = flipY ? node.y + 14 : node.y - height - 12

  return (
    <g className="netmap__callout" transform={`translate(${x} ${y})`} pointerEvents="none">
      <rect className="netmap__calloutbg" width={width} height={height} rx="6" />
      <text className="netmap__calloutname" x={pad} y={pad + size} style={{ fontSize: size * 1.05 }}>
        {node.name}
      </text>
      {rows.map((row, index) => (
        <text
          key={row}
          className={`netmap__calloutmeta ${isStart && index === rows.length - 1 ? 'is-start' : ''}`}
          x={pad}
          y={pad + size * 1.25 + (index + 1) * lineHeight}
          style={{ fontSize: size * 0.88 }}
        >
          {row}
        </text>
      ))}
    </g>
  )
}

/** Map labels drop the generic suffix. The callout always shows the full name. */
function shortName(name) {
  return name
    .replace(/ Nuclear Power Station$/i, '')
    .replace(/ (Substation|Power House|Power Station|Generating Station)$/i, '')
    .replace(/ Wind-Solar Hybrid Cluster$/i, '')
    .replace(/ (Wind|Solar) Cluster$/i, '')
    .replace(/ Underground$/i, '')
    .replace(/ \(.*\)$/, '')
    .replace(/ Dam$/i, '')
}
