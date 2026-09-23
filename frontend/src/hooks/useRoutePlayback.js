/**
 * Route playback.
 *
 * The tour is already computed by the time this runs. Nothing here touches the
 * solvers, the API or any reported figure: it only paces how the finished route
 * is drawn, so a viewer can follow the traversal station by station.
 *
 * Performance: the clock runs on requestAnimationFrame and reports every frame
 * through `onFrame`, which the map uses to write two SVG attributes directly.
 * React state changes only when the *leg* changes, so a 26-leg playback costs
 * 27 renders rather than one per frame.
 *
 * Lifecycle: the clock effect is keyed to a generation counter rather than to
 * the `playing` flag alone. Restarting while already playing would otherwise
 * leave `playing` unchanged, so the effect would not re-run and the cancelled
 * animation frame would never be rescheduled.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/* Playback pacing. Tune here; nothing downstream hardcodes a duration. */
export const LEG_DURATION_MS = 700 // travel time from one station to the next
export const LEG_PAUSE_MS = 200 // dwell on arrival, before the next leg begins
export const SPEEDS = [0.5, 1, 2]
export const DEFAULT_SPEED = 1

const CYCLE_MS = LEG_DURATION_MS + LEG_PAUSE_MS

/*
 * Longest delta a single frame may contribute. Browsers suspend animation
 * frames while a tab is hidden; without this clamp the first frame after
 * returning would carry the entire hidden period and jump the tour forward
 * several stations at once.
 */
const MAX_FRAME_MS = 64

/**
 * Where the tour is at a given elapsed playback time.
 *
 * Pure, so the pacing can be reasoned about and tested without a browser or an
 * animation frame. Each leg is a travel phase followed by a dwell at the
 * station reached, which is what gives the traversal its step-by-step reading.
 */
export function frameFor(elapsedMs, legCount) {
  const totalMs = legCount * CYCLE_MS
  if (legCount <= 0) return { leg: -1, progress: 0, done: true }
  if (elapsedMs >= totalMs) return { leg: legCount - 1, progress: 1, done: true }

  const leg = Math.min(Math.floor(elapsedMs / CYCLE_MS), legCount - 1)
  const within = elapsedMs - leg * CYCLE_MS
  return { leg, progress: Math.min(within / LEG_DURATION_MS, 1), done: false }
}

/** Total wall-clock time a full playback takes at a given speed. */
export function playbackDurationMs(legCount, speed = 1) {
  return (legCount * CYCLE_MS) / speed
}

export function useRoutePlayback({ legCount = 0, routeKey, onFrame, reducedMotion = false }) {
  const [playing, setPlaying] = useState(false)
  const [legIndex, setLegIndex] = useState(-1)
  const [speed, setSpeed] = useState(DEFAULT_SPEED)
  const [finished, setFinished] = useState(false)
  const [generation, setGeneration] = useState(0)

  const frameRef = useRef(0)
  const elapsedRef = useRef(0)
  const lastTickRef = useRef(0)
  const legRef = useRef(-1)
  const onFrameRef = useRef(onFrame)
  const speedRef = useRef(speed)

  onFrameRef.current = onFrame
  speedRef.current = speed

  const emit = useCallback((leg, progress, done) => {
    onFrameRef.current?.({ leg, progress, done })
    if (legRef.current !== leg) {
      legRef.current = leg
      setLegIndex(leg)
    }
  }, [])

  const rewind = useCallback(() => {
    elapsedRef.current = 0
    lastTickRef.current = 0
    legRef.current = -1
    setLegIndex(-1)
    setFinished(false)
  }, [])

  /* Restart whenever the route on screen changes: a new run, or a view switch. */
  useEffect(() => {
    rewind()

    if (!legCount) {
      setPlaying(false)
      return
    }

    if (reducedMotion) {
      // The simpler transition: the finished route, drawn at once.
      setPlaying(false)
      setFinished(true)
      emit(legCount - 1, 1, true)
      return
    }

    emit(-1, 0, false)
    setPlaying(true)
    setGeneration((value) => value + 1)
  }, [routeKey, legCount, reducedMotion, emit, rewind])

  /* The clock. */
  useEffect(() => {
    if (!playing || !legCount || reducedMotion) return undefined

    const totalMs = legCount * CYCLE_MS

    const tick = (now) => {
      if (!lastTickRef.current) lastTickRef.current = now
      const delta = Math.min(now - lastTickRef.current, MAX_FRAME_MS)
      elapsedRef.current += delta * speedRef.current
      lastTickRef.current = now

      const frame = frameFor(elapsedRef.current, legCount)
      emit(frame.leg, frame.progress, frame.done)

      if (frame.done) {
        elapsedRef.current = totalMs
        setPlaying(false)
        setFinished(true)
        return
      }

      frameRef.current = requestAnimationFrame(tick)
    }

    frameRef.current = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frameRef.current)
      lastTickRef.current = 0
    }
  }, [playing, generation, legCount, reducedMotion, emit])

  const play = useCallback(() => {
    if (!legCount || reducedMotion) return
    if (finished) rewind()
    lastTickRef.current = 0
    setPlaying(true)
    setGeneration((value) => value + 1)
  }, [legCount, reducedMotion, finished, rewind])

  const pause = useCallback(() => {
    setPlaying(false)
    lastTickRef.current = 0
  }, [])

  const replay = useCallback(() => {
    if (!legCount || reducedMotion) return
    rewind()
    emit(-1, 0, false)
    setPlaying(true)
    setGeneration((value) => value + 1)
  }, [legCount, reducedMotion, rewind, emit])

  return {
    playing,
    finished,
    legIndex,
    legCount,
    speed,
    setSpeed,
    play,
    pause,
    replay,
  }
}
