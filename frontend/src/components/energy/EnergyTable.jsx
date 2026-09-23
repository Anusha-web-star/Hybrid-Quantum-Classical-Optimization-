/**
 * Energy loss.
 *
 * Two halves with very different standing, kept visibly apart:
 *
 *   Dataset  - Loss_Percent, Energy_Loss_MW, Capacity_MW and Voltage_kV read
 *              straight off each transmission line and shown unchanged.
 *   Derived  - route-level totals and their rupee value, computed by the
 *              backend from those same dataset values and a published tariff.
 *
 * The split matters: nothing in the left half was calculated by anyone, and
 * everything in the right half was. Before a run completes the derived slots
 * stay empty and say so, rather than being filled with a guess.
 *
 * When a route is loaded, the per-line table marks which lines that route
 * actually runs over, so the jump from a line's Energy_Loss_MW to the route
 * total is something the reader can follow row by row.
 */

import { useMemo, useState } from 'react'

import { inr, inrShort, mw } from '../../lib/format.js'
import './EnergyTable.css'

const COLUMNS = [
  { key: 'loss_percent', label: 'Loss %', decimals: 3 },
  { key: 'energy_loss_mw', label: 'Loss MW', decimals: 3 },
  { key: 'capacity_mw', label: 'Capacity MW', decimals: 1 },
  { key: 'voltage_kv', label: 'kV', decimals: 0 },
]

const lineKey = (source, destination) => [source, destination].sort().join('|')

export function EnergyTable({ network, energy }) {
  const lines = network?.transmission_lines ?? []
  const [sort, setSort] = useState({ key: 'loss_percent', dir: 'desc' })

  const coverage = useMemo(
    () =>
      COLUMNS.map((column) => ({
        ...column,
        present: lines.filter((line) => typeof line[column.key] === 'number').length,
      })),
    [lines],
  )

  // Which lines each route runs over, so the per-line rows can be marked.
  const routeLines = useMemo(() => {
    const mark = (route, name) => {
      const map = new Map()
      for (const line of route?.lines_used ?? []) {
        map.set(lineKey(line.source, line.destination), name)
      }
      return map
    }
    const nn = mark(energy?.classical, 'nn')
    const qa = mark(energy?.hybrid, 'qa')
    const merged = new Map()
    for (const [key] of nn) merged.set(key, qa.has(key) ? 'both' : 'nn')
    for (const [key] of qa) if (!merged.has(key)) merged.set(key, 'qa')
    return merged
  }, [energy])

  const derived = useMemo(() => {
    if (!energy) return null
    const { classical, hybrid } = energy
    const networkLoss = lines.reduce(
      (total, line) =>
        typeof line.energy_loss_mw === 'number' ? total + line.energy_loss_mw : total,
      0,
    )
    return [
      {
        label: 'Classical NN route loss',
        value: mw(classical.total_energy_loss_mw),
        sub: `${inrShort(classical.loss_cost_per_hour_inr)}/h · ${classical.line_count} lines`,
      },
      {
        label: 'Hybrid QAOA route loss',
        value: mw(hybrid.total_energy_loss_mw),
        sub: `${inrShort(hybrid.loss_cost_per_hour_inr)}/h · ${hybrid.line_count} lines`,
      },
      {
        label: 'Loss difference',
        value: mw(energy.energy_loss_difference_mw),
        sub: `${inrShort(energy.hourly_cost_difference_inr)}/h · NN minus hybrid`,
      },
      {
        label: 'Network total loss',
        value: mw(networkLoss),
        sub: `all ${lines.length} lines, whether routed or not`,
      },
    ]
  }, [energy, lines])

  const sorted = useMemo(() => {
    const rows = [...lines]
    rows.sort((a, b) => {
      const left = a[sort.key]
      const right = b[sort.key]
      if (typeof left !== 'number') return 1
      if (typeof right !== 'number') return -1
      return sort.dir === 'asc' ? left - right : right - left
    })
    return rows
  }, [lines, sort])

  if (lines.length === 0) return <p className="blank">Network not loaded.</p>

  return (
    <div className="energy">
      <div className="energy__top">
        <div className="energy__coverage">
          <p className="cap">From the dataset</p>
          <div className="energy__cov">
            {coverage.map((column) => (
              <span key={column.key} className="cov">
                <span className="cov__n num">
                  {column.present}/{lines.length}
                </span>
                <span className="cov__k mono">{column.label}</span>
              </span>
            ))}
          </div>
        </div>

        <div className="energy__absent">
          <p className="cap">
            {derived ? 'Calculated from the route' : 'Calculated once a run completes'}
          </p>
          <div className="energy__abs">
            {derived
              ? derived.map((item) => (
                  <span key={item.label} className="abs is-filled">
                    <span className="abs__v mono">{item.value}</span>
                    <span className="abs__k">{item.label}</span>
                    <span className="abs__s mono">{item.sub}</span>
                  </span>
                ))
              : [
                  'Classical NN route loss',
                  'Hybrid QAOA route loss',
                  'Loss difference',
                  'Network total loss',
                ].map((label) => (
                  <span key={label} className="abs">
                    <span className="abs__v mono">--</span>
                    <span className="abs__k">{label}</span>
                  </span>
                ))}
          </div>
          {energy && (
            <p className="energy__note">
              Route loss sums each line's own <span className="mono">Energy_Loss_MW</span> once
              per distinct line used - it is a steady-state property of the line, so a line
              crossed twice is still counted once. Priced at{' '}
              <span className="mono">{inr(energy.tariff.inr_per_kwh)}/kWh</span>, the{' '}
              {energy.tariff.category} energy charge from the {energy.tariff.authority} order
              of {energy.tariff.order_date}. Energy charge only - fixed charges, FPPCA, taxes
              and other billing components are excluded.
            </p>
          )}
        </div>
      </div>

      <div className="energy__tablewrap">
        <table className="energy__table">
          <thead>
            <tr>
              <th scope="col">Transmission line</th>
              {energy && <th scope="col">On route</th>}
              {COLUMNS.map((column) => (
                <th key={column.key} scope="col">
                  <button
                    type="button"
                    className={`energy__sort ${sort.key === column.key ? 'is-on' : ''}`}
                    onClick={() =>
                      setSort((current) =>
                        current.key === column.key
                          ? { key: column.key, dir: current.dir === 'asc' ? 'desc' : 'asc' }
                          : { key: column.key, dir: 'desc' },
                      )
                    }
                  >
                    {column.label}
                    {sort.key === column.key && (
                      <span aria-hidden="true">{sort.dir === 'asc' ? '▲' : '▼'}</span>
                    )}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((line) => {
              const used = routeLines.get(lineKey(line.source, line.destination))
              return (
                <tr key={`${line.source}|${line.destination}`} className={used ? 'is-used' : ''}>
                  <th scope="row">
                    {line.source} <span className="energy__to">to</span> {line.destination}
                  </th>
                  {energy && (
                    <td className="energy__on">
                      {used ? <span className={`tag tag--${used}`}>{USED_LABEL[used]}</span> : '-'}
                    </td>
                  )}
                  {COLUMNS.map((column) => (
                    <td key={column.key} className="num">
                      {typeof line[column.key] === 'number'
                        ? line[column.key].toFixed(column.decimals)
                        : '-'}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const USED_LABEL = { nn: 'NN', qa: 'QAOA', both: 'both' }
