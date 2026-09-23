# frontend/

The GRIDOPT control panel. A React client for the Phase 3 FastAPI backend.

No solver logic lives here. Every distance, route, validation check and
comparison figure is fetched from the API, which runs the existing Phase 1 and
Phase 2 code. The station list is fetched too, never hardcoded.

## Running it

Start the backend first, from the repository root:

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend
```

Then, from `frontend/`:

```bash
npm install
```

```bash
npm run dev
```

Open <http://localhost:5173>. The dev server proxies `/stations`, `/network`,
`/solve`, `/graphs`, `/health` and `/dataset` to `http://127.0.0.1:8000`, so the
browser stays on one origin. Point the proxy elsewhere with `VITE_API_TARGET`,
or bypass it with `VITE_API_BASE`.

## Layout

One fixed-height surface. The page never scrolls; the regions inside it do.

```
rail      GRIDOPT, live network facts, backend state
main      control column  |  network canvas  |  results column
drawer    Routes | Energy loss | Figures | Method
```

Everything needed to run and read an optimization is in the first view: origin
selector, depth, run control, status, the network, and both results. Detail and
methodology live in the drawer, collapsed to a 40px strip until asked for.

```
src/
  api/          client.js      fetch, error normalization, ApiError
                gridopt.js     one function per endpoint
  hooks/        useNetwork     loads stations + network once
                useOptimization  drives a run, owns its status and log
  lib/          geo.js         projection, label de-collision, route polylines
                format.js      km / % / duration formatting
  components/
    shell/      Rail, Drawer, DrawerPanels
    control/    ControlColumn, StartStationSelect
    network/    NetworkCanvas, NetworkMap
    results/    ResultsColumn, RouteScrubber
    energy/     EnergyTable
    common/     CountUp, States
  styles/       tokens.css     colour, type, space, radius, motion
                base.css       reset and shared primitives
```

`App.jsx` composes the three regions and routes state between the hooks and the
components.

## Design system

Instrument panel, not a document. Dials: `DESIGN_VARIANCE 7`,
`MOTION_INTENSITY 4`, `VISUAL_DENSITY 8`.

- **Type.** Geist and Geist Mono, self-hosted through `@fontsource-variable`.
- **Accent lock.** Amber is the only accent. It reads as instrument
  illumination and keeps the UI away from the default blue and violet glow.
- **Data encoding.** The one place a second hue is allowed: the classical tour
  is near-white, the hybrid tour is amber, the network beneath both is dim
  grey. Three values, three weights, legible without consulting the legend.
- **Radius lock.** Surfaces 10px, controls 8px, segmented toggles full pill.
  Nothing else.
- **Density.** At this density metrics sit in plain layout grouped by
  hairlines, not in card containers.
- **Icons.** Phosphor only. No hand-drawn glyphs. The three inline `<path>`
  elements are data marks (the map graticule and the two route polylines), not
  icons.
- **Motion.** Five looping animations, each tied to real ongoing state: three
  in-flight spinners, the running stage, and the pending-result shimmer.
  Nothing loops for decoration. Everything honours `prefers-reduced-motion`.

## Honest reporting

Two rules the UI keeps:

- **No invented progress.** The backend reports no completion fraction, so the
  running stage is indeterminate and the only moving number is real elapsed
  time. A stage advances only when a call actually returned.
- **No invented values.** Energy shows the CSV's own `Loss_Percent`,
  `Energy_Loss_MW`, `Capacity_MW` and `Voltage_kV` verbatim. Route-level and
  aggregate energy figures have no backend endpoint yet, so those slots are
  laid out and marked as not computed rather than filled in by the client.

## Execution mode

Every run uses the local Aer simulator, because that is all the API offers. The
client has no mode switch and no way to request IBM Quantum hardware.
