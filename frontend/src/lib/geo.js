/**
 * Projecting the network onto the map.
 *
 * The stations carry real latitude and longitude, so the map is a true
 * geographic plot rather than a force layout - the same choice the Phase 1/2
 * renderers make, which keeps the browser map and the generated PNGs
 * recognisably the same picture.
 */

/**
 * Equirectangular projection with a cosine correction on longitude.
 *
 * At Karnataka's latitude a degree of longitude is noticeably shorter than a
 * degree of latitude; without the correction the state comes out stretched.
 */
export function createProjection(stations, { width, height, padding = 54 }) {
  const points = stations.filter(
    (station) => typeof station.latitude === 'number' && typeof station.longitude === 'number',
  )

  if (points.length === 0) {
    return { project: () => ({ x: width / 2, y: height / 2 }), ok: false }
  }

  const lats = points.map((p) => p.latitude)
  const lons = points.map((p) => p.longitude)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)

  const midLat = (minLat + maxLat) / 2
  const lonScale = Math.cos((midLat * Math.PI) / 180)

  const spanX = Math.max((maxLon - minLon) * lonScale, 1e-6)
  const spanY = Math.max(maxLat - minLat, 1e-6)

  const innerW = Math.max(width - padding * 2, 1)
  const innerH = Math.max(height - padding * 2, 1)

  // One scale for both axes keeps the geography undistorted.
  const scale = Math.min(innerW / spanX, innerH / spanY)
  const offsetX = padding + (innerW - spanX * scale) / 2
  const offsetY = padding + (innerH - spanY * scale) / 2

  const project = (station) => {
    if (typeof station?.latitude !== 'number' || typeof station?.longitude !== 'number') {
      return null
    }
    return {
      x: offsetX + (station.longitude - minLon) * lonScale * scale,
      y: offsetY + (maxLat - station.latitude) * scale, // north at the top
    }
  }

  return { project, ok: true, bounds: { minLat, maxLat, minLon, maxLon } }
}

/** name -> {x, y}, so route drawing is a lookup rather than a search. */
export function buildPointIndex(stations, project) {
  const index = new Map()
  stations.forEach((station) => {
    const point = project(station)
    if (point) index.set(station.name, point)
  })
  return index
}

/**
 * The physical polyline a tour follows.
 *
 * A leg between two stations may be routed through others - the solvers
 * optimise over shortest-path costs - so the drawn path follows
 * `origin -> via… -> destination` and shows the network as actually traversed.
 */
export function routePolyline(legs, points) {
  if (!Array.isArray(legs) || legs.length === 0) return ''

  const coordinates = []
  legs.forEach((leg, index) => {
    const hops = [leg.origin, ...(leg.via ?? []), leg.destination]
    hops.forEach((name, hop) => {
      if (index > 0 && hop === 0) return // the previous leg already ended here
      const point = points.get(name)
      if (point) coordinates.push(point)
    })
  })

  if (coordinates.length === 0) return ''
  return coordinates.map(({ x, y }, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
}

/** Approximate length of a path, used to time the draw-on animation. */
export function polylineLength(pathData) {
  const numbers = pathData.match(/-?\d+(?:\.\d+)?/g)
  if (!numbers || numbers.length < 4) return 0
  let total = 0
  for (let i = 2; i < numbers.length - 1; i += 2) {
    const dx = Number(numbers[i]) - Number(numbers[i - 2])
    const dy = Number(numbers[i + 1]) - Number(numbers[i - 1])
    total += Math.hypot(dx, dy)
  }
  return total
}

/**
 * The drawn route, plus where each leg begins and ends along it.
 *
 * `routePolyline` gives the shape; this adds the cumulative arc length at every
 * leg boundary, which is what lets playback map "leg 7, 40% of the way across"
 * onto an exact distance along the path. The path is polyline-only, so summing
 * segment lengths is exact rather than an approximation.
 */
export function routeGeometry(legs, points) {
  if (!Array.isArray(legs) || legs.length === 0) return null

  const coordinates = []
  const legEndIndex = []

  legs.forEach((leg, index) => {
    const hops = [leg.origin, ...(leg.via ?? []), leg.destination]
    hops.forEach((name, hop) => {
      if (index > 0 && hop === 0) return
      const point = points.get(name)
      if (point) coordinates.push(point)
    })
    legEndIndex.push(coordinates.length - 1)
  })

  if (coordinates.length < 2) return null

  // Arc length at each vertex.
  const atVertex = [0]
  for (let i = 1; i < coordinates.length; i += 1) {
    const dx = coordinates[i].x - coordinates[i - 1].x
    const dy = coordinates[i].y - coordinates[i - 1].y
    atVertex.push(atVertex[i - 1] + Math.hypot(dx, dy))
  }

  const d = coordinates
    .map(({ x, y }, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ')

  return {
    d,
    total: atVertex[atVertex.length - 1],
    // Distance along the path at the end of each leg, so legEnds[i] is where
    // the tour arrives at the i-th destination.
    legEnds: legEndIndex.map((vertex) => atVertex[vertex]),
    legCount: legs.length,
  }
}
