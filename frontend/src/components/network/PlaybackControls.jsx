/**
 * Playback transport for the route traversal.
 *
 * Play, pause, replay and a speed selector, plus a readout of which station the
 * tour is arriving at. This paces the drawing of a route that is already
 * computed; it has no bearing on the solvers or on any reported figure.
 */

import { ArrowCounterClockwise, Pause, Play } from '@phosphor-icons/react'

import { SPEEDS } from '../../hooks/useRoutePlayback.js'
import './PlaybackControls.css'

export function PlaybackControls({ playback, reducedMotion, currentStation, start }) {
  const { playing, finished, legIndex, legCount, speed, setSpeed, play, pause, replay } = playback

  if (reducedMotion) {
    return (
      <div className="transport transport--static">
        <span className="transport__reduced mono">
          reduced motion: route shown complete
        </span>
      </div>
    )
  }

  const step = Math.max(legIndex + 1, 0)
  const arriving = currentStation ?? start

  return (
    <div className="transport">
      <button
        type="button"
        className="transport__btn transport__btn--primary"
        onClick={playing ? pause : play}
        aria-label={playing ? 'Pause route playback' : 'Play route playback'}
      >
        {playing ? <Pause size={13} weight="fill" /> : <Play size={13} weight="fill" />}
      </button>

      <button
        type="button"
        className="transport__btn"
        onClick={replay}
        aria-label="Replay route from the origin"
      >
        <ArrowCounterClockwise size={13} weight="bold" />
      </button>

      <div className="transport__readout">
        <span className="transport__step mono">
          {String(step).padStart(2, '0')}/{legCount}
        </span>
        <span className="transport__station" title={arriving ?? ''}>
          {finished ? 'tour closed' : (arriving ?? 'ready')}
        </span>
      </div>

      <div className="transport__progress" aria-hidden="true">
        <span
          className="transport__progressfill"
          style={{ width: `${legCount ? (step / legCount) * 100 : 0}%` }}
        />
      </div>

      <div className="transport__speeds" role="group" aria-label="Playback speed">
        {SPEEDS.map((value) => (
          <button
            key={value}
            type="button"
            className={`transport__speed ${speed === value ? 'is-on' : ''}`}
            onClick={() => setSpeed(value)}
            aria-pressed={speed === value}
          >
            {value}x
          </button>
        ))}
      </div>
    </div>
  )
}
