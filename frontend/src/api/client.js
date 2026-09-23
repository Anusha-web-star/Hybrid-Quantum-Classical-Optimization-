/**
 * Low-level HTTP client for the GRIDOPT FastAPI backend.
 *
 * The only place in the app that knows about fetch, status codes or the API
 * base URL. Everything above it works with plain objects and `ApiError`.
 *
 * Every request is authorized here, once, from the current Supabase session:
 * the access token is attached as `Authorization: Bearer <jwt>` so no component
 * has to think about auth. The backend verifies that token on every protected
 * endpoint under AUTH_MODE=supabase, so a stale or missing session surfaces as
 * a normal `ApiError` rather than as bad data.
 */

import { supabase } from '../lib/supabase.js'

const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

/**
 * The Authorization header for the current session, or nothing.
 *
 * `getSession()` reads the session the library already holds and refreshes the
 * token if it is close to expiry; it does not make a round trip per call. A
 * failure here is deliberately swallowed - the request proceeds without a token
 * and the backend answers 401, which is handled like any other API error. The
 * token is never logged and never put in a URL.
 */
async function authHeader() {
  if (!supabase) return {}
  try {
    const { data } = await supabase.auth.getSession()
    const token = data?.session?.access_token
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

/** A failed request, carrying whatever the backend was able to tell us. */
export class ApiError extends Error {
  constructor(message, { status = 0, code = 'request_failed', detail = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }

  /** True when the user can fix this by choosing a different station. */
  get isStartStationProblem() {
    return (
      this.code === 'unknown_start_station' || this.code === 'ambiguous_start_station'
    )
  }
}

export function apiUrl(path) {
  return `${BASE}${path}`
}

/**
 * Turn a FastAPI error body into an ApiError.
 *
 * The backend answers with `detail` as either a string, one of our structured
 * objects, or Pydantic's validation array. All three are normalized here so no
 * component has to branch on shape.
 */
function toApiError(status, body) {
  const detail = body?.detail

  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return new ApiError(detail.message || 'The request could not be completed.', {
      status,
      code: detail.error || 'request_failed',
      detail,
    })
  }

  if (Array.isArray(detail)) {
    const first = detail[0]
    const field = first?.loc?.filter((part) => part !== 'body').join('.') || 'request'
    return new ApiError(`${field}: ${first?.msg ?? 'is invalid'}`, {
      status,
      code: 'validation_error',
      detail,
    })
  }

  return new ApiError(
    typeof detail === 'string' ? detail : `Request failed (HTTP ${status}).`,
    { status, code: 'request_failed', detail },
  )
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const headers = await authHeader()
  if (body) headers['Content-Type'] = 'application/json'

  let response
  try {
    response = await fetch(apiUrl(path), {
      method,
      signal,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    throw new ApiError(
      'Cannot reach the GRIDOPT API. Start the FastAPI backend and try again.',
      { code: 'network_unreachable' },
    )
  }

  if (!response.ok) {
    let parsed = null
    try {
      parsed = await response.json()
    } catch {
      /* a non-JSON error body tells us nothing extra; fall through */
    }
    throw toApiError(response.status, parsed)
  }

  if (response.status === 204) return null
  return response.json()
}

export const get = (path, options) => request(path, options)
export const post = (path, body, options) => request(path, { ...options, method: 'POST', body })
