/** Number and unit formatting. One place, so every readout agrees. */

export const km = (value, decimals = 3) =>
  typeof value === 'number' ? `${value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} km` : '-'

export const percent = (value, decimals = 2) =>
  typeof value === 'number' ? `${value.toFixed(decimals)}%` : '-'

/** Execution time, scaled to whichever unit reads naturally. */
export const duration = (seconds) => {
  if (typeof seconds !== 'number') return '-'
  if (seconds < 0.001) return `${(seconds * 1e6).toFixed(0)} µs`
  if (seconds < 1) return `${(seconds * 1000).toFixed(3)} ms`
  if (seconds < 60) return `${seconds.toFixed(2)} s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${(seconds % 60).toFixed(0)}s`
}

export const elapsed = (ms) => {
  if (typeof ms !== 'number') return '0.0s'
  return `${(ms / 1000).toFixed(1)}s`
}

export const signedKm = (value, decimals = 3) =>
  typeof value === 'number'
    ? `${value > 0 ? '+' : ''}${value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })} km`
    : '-'

export const signedPercent = (value, decimals = 2) =>
  typeof value === 'number' ? `${value > 0 ? '+' : ''}${value.toFixed(decimals)}%` : '-'

/** Modeled power loss, in megawatts. */
export const mw = (value, decimals = 3) =>
  typeof value === 'number' ? `${value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} MW` : '-'

export const signedMw = (value, decimals = 3) =>
  typeof value === 'number'
    ? `${value > 0 ? '+' : ''}${value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })} MW`
    : '-'

/** Rupees in full, grouped the Indian way (1,00,000 rather than 100,000). */
export const inr = (value, decimals = 2) =>
  typeof value === 'number' ? `₹${value.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}` : '-'

/**
 * Rupees on the Indian short scale - thousand, lakh, crore.
 *
 * Loss costs here run to billions of rupees a year, which is unreadable in
 * full. The exact figure stays available in the panel and in the API.
 */
export const inrShort = (value) => {
  if (typeof value !== 'number') return '-'
  const sign = value < 0 ? '-' : ''
  const size = Math.abs(value)
  if (size >= 1e7) return `${sign}₹${(size / 1e7).toFixed(2)} Cr`
  if (size >= 1e5) return `${sign}₹${(size / 1e5).toFixed(2)} L`
  if (size >= 1e3) return `${sign}₹${(size / 1e3).toFixed(2)} K`
  return `${sign}₹${size.toFixed(2)}`
}

export const signedInrShort = (value) =>
  typeof value === 'number'
    ? `${value > 0 ? '+' : ''}${inrShort(value)}`
    : '-'

export const compact = (value, decimals = 1) =>
  typeof value === 'number'
    ? value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })
    : '-'
