/**
 * Loads the station and network data once and shares it with the whole app.
 *
 * The station list is never hardcoded: it is exactly what `/stations` and
 * `/network` return, so the dashboard cannot drift from the CSV.
 */

import { useCallback, useEffect, useState } from 'react'

import { fetchNetwork, fetchStations } from '../api/gridopt.js'

export function useNetwork() {
  const [state, setState] = useState({
    status: 'loading',
    stations: [],
    network: null,
    error: null,
  })

  const load = useCallback((signal) => {
    setState((previous) => ({ ...previous, status: 'loading', error: null }))

    Promise.all([fetchStations(signal), fetchNetwork(signal)])
      .then(([stationList, network]) => {
        if (signal?.aborted) return
        setState({
          status: 'ready',
          stations: stationList.stations,
          network,
          error: null,
        })
      })
      .catch((error) => {
        if (signal?.aborted || error?.name === 'AbortError') return
        setState({ status: 'error', stations: [], network: null, error })
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  return { ...state, reload: () => load() }
}
