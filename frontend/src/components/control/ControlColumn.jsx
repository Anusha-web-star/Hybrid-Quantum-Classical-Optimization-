/**
 * The left column: everything needed to start a run, and what it is doing.
 *
 * Origin, depth, run, status. No card containers, no eyebrow above each block;
 * the column is one surface divided by hairlines, which is what lets all four
 * fit above the fold at this density.
 */

import { ArrowClockwise, CircleNotch, Play, Warning } from '@phosphor-icons/react'

import { RUN_PROFILES } from '../../hooks/useOptimization.js'
import { SamplingField } from './SamplingField.jsx'
import { elapsed, signedKm, signedPercent } from '../../lib/format.js'
import { StartStationSelect } from './StartStationSelect.jsx'
import './ControlColumn.css'

const STAGE_NAME = {
  classical: 'Nearest Neighbour',
  hybrid: 'QAOA loop',
  comparison: 'Comparison',
  graphs: 'Figures',
}

export function ControlColumn({ stations, start, onStartChange, optimization, ready, qaoa }) {
  const { status, stage, stages, log, elapsedMs, error, result, isRunning, run, reset } =
    optimization

  return (
    <aside className="control">
      <section className="control__block">
        <p className="cap">Origin station</p>
        <StartStationSelect
          stations={stations}
          value={start}
          onChange={onStartChange}
          disabled={!ready || isRunning}
        />
      </section>

      <section className="control__block">
        <div className="depth">
          {Object.values(RUN_PROFILES).map((profile) => {
            const on = optimization.profileId === profile.id
            return (
              <button
                key={profile.id}
                type="button"
                className={`depth__opt ${on ? 'is-on' : ''}`}
                disabled={!ready || isRunning}
                onClick={() => optimization.setProfileId(profile.id)}
                aria-pressed={on}
              >
                <span className="depth__name">{profile.label}</span>
                <span className="depth__spec mono">{profile.spec}</span>
                <span className="depth__eta mono">{profile.estimate}</span>
              </button>
            )
          })}
        </div>

        <button
          type="button"
          className={`runbtn ${isRunning ? 'is-busy' : ''}`}
          disabled={!ready || !start || isRunning}
          onClick={() => run(start, optimization.profileId)}
        >
          {isRunning ? (
            <CircleNotch size={15} weight="bold" className="runbtn__spin" />
          ) : status === 'success' ? (
            <ArrowClockwise size={15} weight="bold" />
          ) : (
            <Play size={15} weight="fill" />
          )}
          {isRunning ? 'Optimizing' : status === 'success' ? 'Run again' : 'Run optimization'}
          {isRunning && <span className="runbtn__clock mono">{elapsed(elapsedMs)}</span>}
        </button>
      </section>

      <section className="control__block control__block--grow">
        <div className="control__statushead">
          <p className="cap">Status</p>
          {status === 'success' && result && (
            <button type="button" className="control__clear" onClick={reset}>
              clear
            </button>
          )}
        </div>

        <ol className="stages">
          {stages.map((id, index) => {
            const current = stage ? stages.indexOf(stage) : -1
            const done = status === 'success' || (current > -1 && index < current)
            const active = status === 'running' && index === current
            const failed = status === 'error' && index === current
            return (
              <li
                key={id}
                className={`stage ${done ? 'is-done' : ''} ${active ? 'is-active' : ''} ${
                  failed ? 'is-failed' : ''
                }`}
              >
                <span className="stage__tick" />
                <span className="stage__name">{STAGE_NAME[id]}</span>
              </li>
            )
          })}
        </ol>

        <SamplingField
          active={status === 'running' && stage === 'hybrid'}
          qubits={qaoa?.qubits}
          shots={qaoa?.shots}
        />

        <div className="log scroll-y" role="log" aria-live="polite">
          {log.length === 0 ? (
            <p className="log__line log__line--idle">
              Pick an origin, then run. Both solvers execute in the backend.
            </p>
          ) : (
            log.map((entry) => (
              <p key={entry.id} className={`log__line log__line--${entry.tone}`}>
                {entry.text}
              </p>
            ))
          )}
        </div>

        {status === 'error' && error && (
          <div className="control__error" role="alert">
            <Warning size={15} weight="fill" />
            <div>
              <p className="control__errortitle">
                {error.isStartStationProblem ? 'Origin not usable' : 'Run failed'}
              </p>
              <p className="control__errorbody">{error.message}</p>
              {error.code === 'network_unreachable' && (
                <p className="control__errorhint mono">
                  uvicorn app.main:app --app-dir backend
                </p>
              )}
            </div>
          </div>
        )}

        {status === 'success' && result && (
          <p className="control__verdict">
            {result.comparison.winner === 'hybrid' ? (
              <>
                Hybrid tour is{' '}
                <strong>{signedKm(result.comparison.improvement_km)}</strong> shorter,{' '}
                {signedPercent(result.comparison.improvement_percent)} against the classical
                baseline.
              </>
            ) : result.comparison.winner === 'tie' ? (
              'Both solvers returned tours of equal length.'
            ) : (
              <>
                Classical baseline held this run by{' '}
                <strong>{signedKm(Math.abs(result.comparison.improvement_km))}</strong>.
              </>
            )}
          </p>
        )}
      </section>
    </aside>
  )
}
