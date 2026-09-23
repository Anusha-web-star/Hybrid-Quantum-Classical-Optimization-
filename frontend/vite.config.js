import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI backend runs on :8000. Proxying it through the dev server keeps
// the browser on one origin, so CORS never enters the picture during
// development and the client can use plain relative URLs.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

const API_ROUTES = [
  '/stations',
  '/network',
  '/solve',
  '/graphs',
  '/health',
  '/dataset',
  '/assistant',
]

/*
 * When the backend is not listening, http-proxy fails the request and Vite
 * answers with a bare `500 Internal Server Error` and an empty text/plain
 * body. The client cannot parse that, so it falls back to its generic
 * "Request failed (HTTP 500)" - which blames the server for a run that never
 * started, and sends you looking for a bug in the endpoint.
 *
 * Answer in the shape the API uses for its own errors instead, with the code
 * the UI already recognises. `502 Bad Gateway` is the honest status: this
 * proxy is up, the service behind it is not.
 */
function reportUnreachableBackend(proxy) {
  proxy.on('error', (cause, _req, res) => {
    if (!res || res.headersSent || typeof res.writeHead !== 'function') return

    res.writeHead(502, { 'Content-Type': 'application/json' })
    res.end(
      JSON.stringify({
        detail: {
          error: 'network_unreachable',
          message: `Cannot reach the GRIDOPT API at ${API_TARGET} (${cause.code || cause.message}). Start the FastAPI backend and retry.`,
        },
      }),
    )
  })
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_ROUTES.map((route) => [
        route,
        {
          target: API_TARGET,
          changeOrigin: true,
          configure: reportUnreachableBackend,
          /*
           * Two endpoints here are legitimately slow, and both would otherwise
           * depend on http-proxy's defaults rather than on a decision: the
           * hybrid solver runs ~90s, and the assistant runs a local model on
           * CPU, where prompt processing alone can take tens of seconds. A
           * proxy that gave up mid-generation would surface as a dead request
           * in the browser while the backend was still working perfectly.
           *
           * Set generously and explicitly, above the backend's own
           * ASSISTANT_TIMEOUT_S (180s), so the backend's timeout is the one
           * that fires and the browser gets its real error message.
           */
          timeout: 300000,
          proxyTimeout: 300000,
        },
      ]),
    ),
  },
})
