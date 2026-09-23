/**
 * The GRIDOPT API surface, one function per endpoint.
 *
 * Nothing here computes a route, a distance or a comparison - those come from
 * the Phase 1 and Phase 2 solvers behind the API. This module only names the
 * endpoints and passes values through.
 */

import { apiUrl, get, post } from './client.js'

/** Every station in the dataset. */
export const fetchStations = (signal) => get('/stations', { signal })

/** The network summary and all transmission lines. */
export const fetchNetwork = (signal) => get('/network', { signal })

/** Check a starting station without running a solver. */
export const resolveStart = (start, signal) =>
  post('/stations/resolve', { start }, { signal })

/** Phase 1 Nearest Neighbour. Answers in milliseconds. */
export const solveClassical = (start, signal) =>
  post('/solve/classical', { start }, { signal })

/** Phase 2 hybrid QAOA on the local simulator. Slow by nature. */
export const solveHybrid = (start, options = {}, signal) =>
  post('/solve/hybrid', { start, ...options }, { signal })

/**
 * Both solvers plus the comparison, and the three generated images.
 *
 * This is the endpoint the dashboard's Run Optimization button uses: it
 * guarantees both tours came from the same network and the same start.
 */
export const runComparison = (start, options = {}, signal) =>
  post('/solve/compare', { start, render_graphs: true, ...options }, { signal })

/** Which graph images exist, and where. */
export const fetchGraphs = (signal) => get('/graphs', { signal })

/** Backend liveness, used for the connection indicator. */
export const fetchHealth = (signal) => get('/health', { signal })

/**
 * Browser URL for one generated PNG.
 *
 * `cacheKey` busts the browser cache after a re-run, so the panel never shows
 * the previous optimization's image.
 */
export const graphImageUrl = (name, cacheKey) =>
  apiUrl(`/graphs/${name}${cacheKey ? `?v=${encodeURIComponent(cacheKey)}` : ''}`)

/**
 * Ask the grounded project assistant.
 *
 * `run` is the whole `/solve/compare` body the dashboard is currently showing,
 * passed straight back so the assistant can answer about the actual run rather
 * than about runs in general. Omit it and the assistant says it has no solver
 * results, which is the truth.
 *
 * No key, no model and no provider appears anywhere on this side: the browser
 * sends a question and receives an answer.
 */
export const askAssistant = (question, run, signal) =>
  post('/assistant/query', run ? { question, run } : { question }, { signal })

/** Whether the assistant has a knowledge base and a model. */
export const fetchAssistantStatus = (signal) => get('/assistant/status', { signal })
