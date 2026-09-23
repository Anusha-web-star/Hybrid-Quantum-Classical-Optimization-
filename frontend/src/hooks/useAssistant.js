/**
 * Drives the assistant panel: one question in flight at a time, and a
 * transcript of what has actually been answered.
 *
 * Two things this hook is careful about, both for the same reason - the panel
 * must never show something the backend did not say:
 *
 *   1. A pending turn holds no answer text at all. The panel renders a loading
 *      state from `status`, never a placeholder answer that gets overwritten.
 *   2. `grounded` comes from the backend and is passed through untouched. When
 *      it is false the answer is the project's unavailable line, and the panel
 *      is expected to mark it as such rather than dressing it up as a result.
 *
 * Asking again cancels the previous request, so a slow answer cannot land after
 * a newer one.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { askAssistant } from '../api/gridopt.js'

/**
 * The seeded questions. Two of them are about the run on screen, so they are
 * only offered once there is a run to ask about - suggesting them with nothing
 * loaded would invite the assistant's "no run attached" answer for no reason.
 */
export const EXAMPLE_QUESTIONS = [
  { text: 'Why did QAOA pick this route over NN?', needsRun: true },
  { text: "What's the estimated annual loss cost for this run?", needsRun: true },
  { text: "What's the loss cost of the RTPS → Bellary leg?", needsRun: false },
  { text: 'Is this transmission distance measured or estimated?', needsRun: false },
  { text: 'How does the hybrid QAOA approach work?', needsRun: false },
]

let nextId = 0

export function useAssistant(run) {
  // One entry per completed exchange: { id, question, answer, sources,
  // grounded, reason, usedSolverContext }.
  const [turns, setTurns] = useState([])
  const [status, setStatus] = useState('idle') // idle | asking | error
  const [pending, setPending] = useState(null) // the question in flight
  const [error, setError] = useState(null)
  const [startedAt, setStartedAt] = useState(null)
  const [elapsedMs, setElapsedMs] = useState(0)
  const abortRef = useRef(null)

  /*
   * A live elapsed clock while a question is in flight.
   *
   * The answer comes from a local model on CPU, where the wait is dominated
   * by prompt processing - tens of seconds, with nothing to show until it
   * finishes. A static label through all of that is indistinguishable from a
   * hang, which is exactly how it was read. Real measured seconds are the
   * honest thing to show: they prove the request is alive without inventing
   * a percentage the backend never reported.
   */
  useEffect(() => {
    if (status !== 'asking' || !startedAt) return undefined
    const tick = () => setElapsedMs(Date.now() - startedAt)
    tick()
    const timer = window.setInterval(tick, 200)
    return () => window.clearInterval(timer)
  }, [status, startedAt])

  // The run is read at ask time, not captured in the callback, so asking about
  // "this run" always means the one currently on screen.
  const runRef = useRef(run)
  runRef.current = run

  useEffect(() => () => abortRef.current?.abort(), [])

  const ask = useCallback(async (question) => {
    const text = (question ?? '').trim()
    if (!text) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setStatus('asking')
    setPending(text)
    setError(null)
    setStartedAt(Date.now())
    setElapsedMs(0)

    try {
      const body = await askAssistant(text, runRef.current, controller.signal)
      if (controller.signal.aborted) return

      setTurns((previous) => [
        ...previous,
        {
          id: (nextId += 1),
          question: text,
          answer: body.answer,
          sources: body.sources ?? [],
          grounded: Boolean(body.grounded),
          reason: body.reason ?? null,
          usedSolverContext: Boolean(body.used_solver_context),
        },
      ])
      setStatus('idle')
      setPending(null)
    } catch (cause) {
      if (controller.signal.aborted || cause?.name === 'AbortError') return
      setError(cause)
      setStatus('error')
    }
  }, [])

  const dismissError = useCallback(() => {
    setError(null)
    setStatus('idle')
    setPending(null)
  }, [])

  const clear = useCallback(() => {
    abortRef.current?.abort()
    setTurns([])
    setStatus('idle')
    setPending(null)
    setError(null)
  }, [])

  return {
    turns,
    status,
    pending,
    error,
    elapsedMs,
    isAsking: status === 'asking',
    hasRun: Boolean(run),
    ask,
    dismissError,
    clear,
  }
}
