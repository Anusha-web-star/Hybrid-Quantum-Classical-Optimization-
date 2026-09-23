/**
 * The QAOA sampling field.
 *
 * Mounted only while the hybrid stage is actually running. That stage is the
 * one genuinely opaque stretch of a run: the simulator is drawing shots and
 * the backend reports no completion fraction, so there is nothing truthful to
 * put on a progress bar. A scrambling field of ones and zeroes is an honest
 * stand-in for what is happening on the other end, and it stops the moment the
 * stage does.
 *
 * It is deliberately a bitstring field rather than the component's default
 * alphabet: QAOA measures bitstrings, so that is what scrolls past.
 *
 * Wraps the vendored React Bits component. All GRIDOPT-specific configuration
 * lives here so the vendored file stays re-syncable.
 */

import { useEffect, useState } from 'react'

import LetterGlitch from '../vendor/LetterGlitch.jsx'
import './SamplingField.css'

/* Tokens, as hex, since the canvas cannot read CSS custom properties. */
const COLORS = ['#8a6529', '#e3a44f', '#c8913c', '#5c4620']
const GROUND = '#08090b'

export function SamplingField({ active, qubits, shots }) {
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!query) return undefined
    const sync = () => setReducedMotion(query.matches)
    sync()
    query.addEventListener?.('change', sync)
    return () => query.removeEventListener?.('change', sync)
  }, [])

  if (!active) return null

  return (
    <div className="sampling">
      <div className="sampling__canvas" aria-hidden="true">
        {reducedMotion ? (
          <div className="sampling__still" />
        ) : (
          <LetterGlitch
            glitchColors={COLORS}
            backgroundColor={GROUND}
            glitchSpeed={44}
            smooth
            outerVignette
            centerVignette={false}
            characters="0101101001100101"
          />
        )}
      </div>

      <p className="sampling__caption mono">
        sampling
        {typeof qubits === 'number' ? ` ${qubits}-qubit circuits` : ' circuits'}
        {typeof shots === 'number' ? `, ${shots.toLocaleString('en-US')} shots` : ''}
      </p>
    </div>
  )
}
