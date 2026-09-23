/**
 * Rendering-layer decluttering for the network map.
 *
 * The dataset places several stations within a few kilometres of each other:
 * the Kali cascade (Supa Dam, Nagjhari, Kodasalli, Kadra, Kaiga), the
 * Sharavathi group (Sharavathy, Linganamakki, Gerusoppa) and the two Raichur
 * thermal stations. At map scale ten pairs land on top of one another.
 *
 * Nothing here touches the data. Coordinates, distances and topology are
 * untouched; this module only decides where to *draw* a node and its label so
 * all 26 remain distinguishable. Every displaced node keeps a faint tether to
 * its true projected position, so the geography stays visible and honest.
 *
 * Both passes are deterministic. No randomness, so a re-render never reshuffles
 * the map.
 */

/**
 * Push overlapping nodes apart while a spring pulls each back to where it
 * actually belongs.
 *
 * The result settles at the smallest displacement that clears the collisions,
 * which keeps a cluster's internal arrangement, and its position relative to
 * the rest of the network, geographically meaningful.
 */
export function declutter(
  entries,
  { minSeparation = 27, iterations = 260, anchorPull = 0.085, maxShift = 30 } = {},
) {
  const nodes = entries.map((entry, index) => ({
    ...entry,
    trueX: entry.x,
    trueY: entry.y,
    index,
  }))

  for (let step = 0; step < iterations; step += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i]
        const b = nodes[j]
        let dx = b.x - a.x
        let dy = b.y - a.y
        let distance = Math.hypot(dx, dy)

        // Exactly coincident points need a deterministic nudge to separate.
        if (distance < 1e-6) {
          const angle = ((i * 7 + j * 13) % 360) * (Math.PI / 180)
          dx = Math.cos(angle)
          dy = Math.sin(angle)
          distance = 1
        }

        if (distance < minSeparation) {
          const push = ((minSeparation - distance) / 2) * 0.5
          const ux = dx / distance
          const uy = dy / distance
          a.x -= ux * push
          a.y -= uy * push
          b.x += ux * push
          b.y += uy * push
        }
      }
    }

    for (const node of nodes) {
      node.x += (node.trueX - node.x) * anchorPull
      node.y += (node.trueY - node.y) * anchorPull
    }
  }

  // Never let a node wander far from the truth, whatever the crowding.
  for (const node of nodes) {
    const dx = node.x - node.trueX
    const dy = node.y - node.trueY
    const shift = Math.hypot(dx, dy)
    if (shift > maxShift) {
      node.x = node.trueX + (dx / shift) * maxShift
      node.y = node.trueY + (dy / shift) * maxShift
    }
    node.shift = Math.hypot(node.x - node.trueX, node.y - node.trueY)
  }

  return nodes
}

/* Where a label may sit relative to its node, in order of preference. */
const DIRECTIONS = [
  { dx: 0, dy: -1, anchor: 'middle', baseline: 'auto' },
  { dx: 0, dy: 1, anchor: 'middle', baseline: 'hanging' },
  { dx: 1, dy: -0.35, anchor: 'start', baseline: 'auto' },
  { dx: -1, dy: -0.35, anchor: 'end', baseline: 'auto' },
  { dx: 1, dy: 0.55, anchor: 'start', baseline: 'hanging' },
  { dx: -1, dy: 0.55, anchor: 'end', baseline: 'hanging' },
  { dx: 0.72, dy: -0.72, anchor: 'start', baseline: 'auto' },
  { dx: -0.72, dy: -0.72, anchor: 'end', baseline: 'auto' },
  { dx: 0.72, dy: 0.72, anchor: 'start', baseline: 'hanging' },
  { dx: -0.72, dy: 0.72, anchor: 'end', baseline: 'hanging' },
]

const RINGS = [1, 1.7, 2.6]

/**
 * Place as many labels as will fit without touching each other or any node.
 *
 * Labels are tried in priority order (the origin first, then the busiest
 * stations) at ten positions around the node and three distances out. A label
 * that has to sit far from its node gets a leader line so the pairing stays
 * unambiguous. Anything that genuinely cannot be placed is left to the hover
 * readout rather than being allowed to overprint a neighbour.
 */
export function placeLabels(nodes, options = {}) {
  const {
    fontSize = 10.5,
    charWidth = 0.58,
    // Tight box around the glyphs, used for bounds and node collision.
    padding = 3,
    // Extra breathing room applied only between labels, so two neighbours
    // never read as one string. Kept separate from `padding` so it does not
    // push every label out to a leader-line ring.
    gutter = 5,
    bounds = { width: 1000, height: 680 },
    priority = () => 0,
    text = (node) => node.name,
    radiusOf = () => 6,
  } = options

  const height = fontSize + padding * 2
  const placed = []
  const results = new Map()

  const ordered = [...nodes].sort((a, b) => priority(b) - priority(a))

  for (const node of ordered) {
    const label = text(node)
    const width = label.length * fontSize * charWidth + padding * 2
    const radius = radiusOf(node)
    let chosen = null

    outer: for (const ring of RINGS) {
      for (const direction of DIRECTIONS) {
        const gap = radius + 7 + (ring - 1) * 11
        const cx = node.x + direction.dx * gap
        const cy = node.y + direction.dy * gap

        const left =
          direction.anchor === 'middle'
            ? cx - width / 2
            : direction.anchor === 'start'
              ? cx - padding
              : cx - width + padding
        const top =
          direction.baseline === 'hanging' ? cy - padding : cy - height + padding

        const box = { left, top, right: left + width, bottom: top + height }

        if (
          box.left < 2 ||
          box.top < 2 ||
          box.right > bounds.width - 2 ||
          box.bottom > bounds.height - 2
        ) {
          continue
        }

        const spaced = {
          left: box.left - gutter,
          top: box.top - gutter * 0.5,
          right: box.right + gutter,
          bottom: box.bottom + gutter * 0.5,
        }
        if (placed.some((other) => overlaps(spaced, other))) continue

        // A label must not cover any station dot either.
        const hitsNode = nodes.some((other) => {
          const r = radiusOf(other) + 2
          return (
            other.x + r > box.left &&
            other.x - r < box.right &&
            other.y + r > box.top &&
            other.y - r < box.bottom
          )
        })
        if (hitsNode) continue

        chosen = {
          x: cx,
          y: cy,
          anchor: direction.anchor,
          baseline: direction.baseline,
          box,
          leader: ring > 1,
        }
        break outer
      }
    }

    if (chosen) {
      placed.push(chosen.box)
      results.set(node.name, chosen)
    }
  }

  return results
}

function overlaps(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
}
