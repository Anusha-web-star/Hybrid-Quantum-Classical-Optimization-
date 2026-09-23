/**
 * Drives one optimization run and everything the UI needs to narrate it.
 *
 * The backend is synchronous - `/solve/compare` returns only when both solvers
 * have finished - so the run is split into two real calls:
 *
 *   1. `/solve/classical`, which answers in milliseconds and lets the Nearest
 *      Neighbour result appear straight away.
 *   2. `/solve/compare`, which runs the hybrid QAOA loop and returns both
 *      tours, the comparison and the rendered graphs.
 *
 * Every status line marks a stage that genuinely completed, and the only
 * number that moves during the hybrid stage is the real elapsed time. Nothing
 * fakes a percentage the backend never reported.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { runComparison, solveClassical } from '../api/gridopt.js'

export const RUN_PROFILES = {
  preview: {
    id: 'preview',
    label: 'Preview',
    spec: 'W=3, 1 sweep',
    estimate: 'about 10s',
    options: { window: 3, sweeps: 1, maxiter: 8, shots: 512 },
  },
  full: {
    id: 'full',
    label: 'Full depth',
    spec: 'W=4, 8 sweeps',
    estimate: 'about 2-3 min',
    options: {},
  },
}

const STAGES = ['classical', 'hybrid', 'comparison', 'graphs']

const initialState = {
  status: 'idle', // idle | running | success | error
  stage: null,
  classicalPreview: null,
  result: null,
  error: null,
  log: [],
  startedAt: null,
  finishedAt: null,
}

export function useOptimization() {
  const [state, setState] = useState(initialState)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [profileId, setProfileId] = useState('full')
  const abortRef = useRef(null)

  // A live elapsed clock while a run is in flight. Real measured time, the
  // only thing that legitimately ticks during the hybrid stage.
  useEffect(() => {
    if (state.status !== 'running' || !state.startedAt) return undefined
    const tick = () => setElapsedMs(Date.now() - state.startedAt)
    tick()
    const timer = window.setInterval(tick, 100)
    return () => window.clearInterval(timer)
  }, [state.status, state.startedAt])

  useEffect(() => () => abortRef.current?.abort(), [])

  const run = useCallback(async (start, profileId = 'full') => {
    const profile = RUN_PROFILES[profileId] ?? RUN_PROFILES.full
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const startedAt = Date.now()

    const append = (text, tone = 'info') =>
      setState((previous) => ({
        ...previous,
        log: [...previous.log, { id: previous.log.length, text, tone, at: Date.now() }],
      }))

    setState({
      ...initialState,
      status: 'running',
      stage: 'classical',
      startedAt,
      log: [
        { id: 0, text: `Origin locked to ${start}`, tone: 'info', at: startedAt },
        {
          id: 1,
          text: `Depth: ${profile.label}, ${profile.spec}`,
          tone: 'dim',
          at: startedAt,
        },
      ],
    })
    setElapsedMs(0)

    try {
      append('Running classical Nearest Neighbour')
      const classical = await solveClassical(start, controller.signal)
      if (controller.signal.aborted) return

      setState((previous) => ({ ...previous, classicalPreview: classical, stage: 'hybrid' }))
      // Distance only. This call and the comparison call each time their own
      // NN solve; quoting one here and the other in the results panel would
      // show two different figures for the same thing.
      append(
        `Classical NN done, ${classical.tour.total_distance_km.toFixed(3)} km`,
        'success',
      )
      append('Running hybrid QAOA on the local Aer simulator')
      append('QAOA runs inside a classical reoptimization loop.', 'dim')

      const comparison = await runComparison(start, profile.options, controller.signal)
      if (controller.signal.aborted) return

      const hybridKm = comparison.hybrid.tour.total_distance_km
      append(
        `Hybrid QAOA done, ${hybridKm.toFixed(3)} km in ` +
          `${comparison.hybrid.tour.execution_time_s.toFixed(2)} s`,
        'success',
      )
      setState((previous) => ({ ...previous, stage: 'comparison' }))
      append('Comparison built, both tours validated on the same network.', 'success')
      setState((previous) => ({ ...previous, stage: 'graphs' }))
      append('Figures rendered.', 'success')

      setState((previous) => ({
        ...previous,
        status: 'success',
        stage: null,
        result: comparison,
        finishedAt: Date.now(),
      }))
    } catch (error) {
      if (controller.signal.aborted || error?.name === 'AbortError') return
      setState((previous) => ({
        ...previous,
        status: 'error',
        stage: null,
        error,
        finishedAt: Date.now(),
        log: [
          ...previous.log,
          { id: previous.log.length, text: error.message, tone: 'error', at: Date.now() },
        ],
      }))
    }
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setState(initialState)
    setElapsedMs(0)
  }, [])

  return {
    ...state,
    elapsedMs,
    isRunning: state.status === 'running',
    stages: STAGES,
    profileId,
    setProfileId,
    run,
    reset,
  }
}
