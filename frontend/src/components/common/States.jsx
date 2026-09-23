/** Loading and error states for the canvas. */

import { ArrowClockwise, CircleNotch, WarningCircle } from '@phosphor-icons/react'

import './States.css'

export function LoadingState({ message = 'Loading' }) {
  return (
    <div className="cstate" role="status" aria-live="polite">
      <CircleNotch size={20} weight="bold" className="cstate__spin" />
      <p className="cstate__msg">{message}</p>
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  const message = error?.message ?? String(error ?? 'Unknown error')
  const suggestions = error?.detail?.suggestions

  return (
    <div className="cstate cstate--error" role="alert">
      <WarningCircle size={22} weight="fill" />
      <div className="cstate__text">
        <p className="cstate__title">Cannot reach the network data</p>
        <p className="cstate__msg">{message}</p>
        {Array.isArray(suggestions) && suggestions.length > 0 && (
          <p className="cstate__msg">Closest matches: {suggestions.slice(0, 4).join(', ')}</p>
        )}
        {error?.code === 'network_unreachable' && (
          <p className="cstate__cmd mono">
            .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend
          </p>
        )}
      </div>
      {onRetry && (
        <button type="button" className="cstate__retry" onClick={onRetry}>
          <ArrowClockwise size={13} weight="bold" />
          Retry
        </button>
      )}
    </div>
  )
}
