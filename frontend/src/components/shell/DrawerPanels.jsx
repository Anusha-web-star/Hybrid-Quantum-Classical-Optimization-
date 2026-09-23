/**
 * What lives inside the drawer.
 *
 * Routes  - both itineraries, complete, as a compact scrubber plus a table.
 * Energy  - dataset attributes verbatim; computed figures marked as absent.
 * Figures - the matplotlib output the backend renders.
 * Method  - the scientific framing, in disclosures rather than paragraphs.
 */

import { useState } from 'react'
import { ArrowSquareOut } from '@phosphor-icons/react'

import { graphImageUrl } from '../../api/gridopt.js'
import { RouteScrubber } from '../results/RouteScrubber.jsx'
import { EnergyTable } from '../energy/EnergyTable.jsx'
import { Disclosure } from './Drawer.jsx'
import './DrawerPanels.css'

export function RoutesPanel({ result }) {
  if (!result) {
    return <Blank>Run an optimization to list both complete itineraries.</Blank>
  }
  return (
    <RouteScrubber
      classical={result.classical.tour}
      quantum={result.hybrid.tour}
    />
  )
}

export function EnergyPanel({ network, energy }) {
  if (!network) return <Blank>Network not loaded.</Blank>
  return <EnergyTable network={network} energy={energy} />
}

export function FiguresPanel({ available, cacheKey }) {
  const [zoom, setZoom] = useState(null)

  if (!available) {
    return <Blank>The backend renders three figures when a comparison finishes.</Blank>
  }

  const figures = [
    { name: 'nn_route', label: 'Classical NN route' },
    { name: 'qaoa_route', label: 'Hybrid QAOA route' },
    { name: 'comparison', label: 'Side by side' },
  ]

  return (
    <>
      <div className="figs">
        {figures.map((figure) => (
          <figure key={figure.name} className="fig">
            <button
              type="button"
              className="fig__frame"
              onClick={() => setZoom(figure)}
              aria-label={`Open ${figure.label} full size`}
            >
              <img
                src={graphImageUrl(figure.name, cacheKey)}
                alt={figure.label}
                loading="lazy"
                decoding="async"
              />
            </button>
            <figcaption className="fig__cap">
              {figure.label}
              <ArrowSquareOut size={11} weight="bold" />
            </figcaption>
          </figure>
        ))}
      </div>

      {zoom && (
        <div
          className="zoom"
          role="dialog"
          aria-modal="true"
          aria-label={zoom.label}
          onClick={() => setZoom(null)}
        >
          <img src={graphImageUrl(zoom.name, cacheKey)} alt={zoom.label} />
        </div>
      )}
    </>
  )
}

export function MethodPanel({ comparison, quantumDetail, network }) {
  const stations = network?.summary?.stations
  const qubits = stations ? (stations - 1) ** 2 : null

  return (
    <div className="method">
      <Disclosure summary="How the hybrid solver actually works" defaultOpen>
        <p>
          QAOA is the optimization engine <strong>inside</strong> a classical full-network
          reoptimization loop. The loop starts from the Nearest Neighbour tour, slides a short
          window along it, and hands each window to QAOA as its own small routing problem.
          Choosing the windows and accepting or rejecting each result is classical.
        </p>
        <p>
          The QAOA subproblems do <strong>not</strong> independently solve the full-network TSP.
          {qubits ? (
            <>
              {' '}Encoding all {stations} stations directly would need ({stations}-1)
              <sup>2</sup> = <code>{qubits}</code> qubits, far beyond both the simulator and
              current hardware.
            </>
          ) : null}
        </p>
        <p>
          <strong>No quantum advantage is claimed.</strong> This is a like-for-like comparison on
          one dataset, not evidence that quantum optimization is faster or better in general.
        </p>
      </Disclosure>

      <Disclosure summary="Why the two results are comparable">
        <p>
          Both solvers receive the identical problem: the same station set, the same origin, and
          the same <code>Distance_km</code> shortest-path cost function. The backend asserts this
          rather than assuming it, and returns the assertions with every comparison.
        </p>
        {comparison && (
          <ul className="method__checks">
            {comparison.same_problem_checks.map((check) => (
              <li key={check.label} className={check.passed ? 'is-ok' : 'is-bad'}>
                {check.label}
              </li>
            ))}
          </ul>
        )}
      </Disclosure>

      <Disclosure summary="Execution mode and configuration">
        <p>
          Every run executes on the local Qiskit Aer simulator. This interface has no hardware
          switch, and the API submits no IBM Quantum job.
        </p>
        {quantumDetail && (
          <dl className="method__spec">
            <div>
              <dt>Backend</dt>
              <dd className="mono">{quantumDetail.backend}</dd>
            </div>
            <div>
              <dt>Window</dt>
              <dd className="mono">
                W={quantumDetail.window}, {quantumDetail.qubits_per_subproblem} qubits per
                subproblem
              </dd>
            </div>
            <div>
              <dt>Sweeps</dt>
              <dd className="mono">{quantumDetail.sweeps_run}</dd>
            </div>
            <div>
              <dt>Subproblems</dt>
              <dd className="mono">
                {quantumDetail.subproblems_solved} solved, {quantumDetail.subproblems_skipped}{' '}
                skipped
              </dd>
            </div>
          </dl>
        )}
      </Disclosure>

      <Disclosure summary="Pipeline">
        <p>
          The transmission-line CSV is the single source of truth. It builds an undirected graph
          whose edge costs are <code>Distance_km</code> shortest paths. Nearest Neighbour produces
          the baseline tour. Each reoptimization window becomes a QUBO, converts to an Ising
          Hamiltonian, and is solved variationally by QAOA. Accepted improvements are folded back
          into the full tour, and both final tours are validated before anything is reported.
        </p>
      </Disclosure>
    </div>
  )
}

function Blank({ children }) {
  return <p className="blank">{children}</p>
}
