/**
 * A number that counts up to its value once, then holds.
 *
 * Borrowed from the Micro Data-Viz treatments: the motion is there to draw the
 * eye to a figure that just changed, so it runs on arrival and on change, and
 * never loops. The final rendered text is always the exact value.
 */

import { useEffect, useRef, useState } from 'react'

const REDUCED = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function CountUp({
  value,
  decimals = 0,
  duration = 900,
  prefix = '',
  suffix = '',
  signed = false,
  className = '',
}) {
  const [shown, setShown] = useState(value)
  const fromRef = useRef(value)
  const frameRef = useRef(0)

  useEffect(() => {
    if (typeof value !== 'number' || Number.isNaN(value)) return undefined
    if (REDUCED()) {
      setShown(value)
      return undefined
    }

    const from = fromRef.current ?? 0
    const start = performance.now()

    const step = (now) => {
      const t = Math.min(1, (now - start) / duration)
      // easeOutExpo: quick to arrive, settles softly on the real figure.
      const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t)
      setShown(from + (value - from) * eased)
      if (t < 1) frameRef.current = requestAnimationFrame(step)
      else fromRef.current = value
    }

    frameRef.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frameRef.current)
  }, [value, duration])

  if (typeof value !== 'number' || Number.isNaN(value)) {
    return <span className={`num ${className}`.trim()}>-</span>
  }

  const text = shown.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  const sign = signed && value > 0 ? '+' : ''

  return (
    <span className={`num ${className}`.trim()}>
      {prefix}
      {sign}
      {text}
      {suffix}
    </span>
  )
}
