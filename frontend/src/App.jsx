/**
 * GRIDOPT.
 *
 * One fixed-height control surface. Rail on top, three columns beneath it, a
 * drawer at the bottom for detail. The page itself never scrolls, so the
 * network, the origin selector, the run control and both results are all in the
 * first view, always.
 *
 * Composition only. Fetching lives in `api/`, run orchestration in
 * `hooks/useOptimization`, rendering in `components/`.
 */

import { useEffect, useMemo, useState } from 'react'

import { AssistantPanel } from './components/assistant/AssistantPanel.jsx'
import { AuthPage } from './components/auth/AuthPage.jsx'
import { IntroAuthBar } from './components/auth/IntroAuthBar.jsx'
import { GridoptIntro } from './components/GridoptIntro.jsx'
import { ControlColumn } from './components/control/ControlColumn.jsx'
import { NetworkCanvas } from './components/network/NetworkCanvas.jsx'
import { ResultsColumn } from './components/results/ResultsColumn.jsx'
import { Drawer } from './components/shell/Drawer.jsx'
import {
  EnergyPanel,
  FiguresPanel,
  MethodPanel,
  RoutesPanel,
} from './components/shell/DrawerPanels.jsx'
import { Rail } from './components/shell/Rail.jsx'
import { useAuth } from './hooks/useAuth.js'
import { useNetwork } from './hooks/useNetwork.js'
import { RUN_PROFILES, useOptimization } from './hooks/useOptimization.js'
import './App.css'

export default function App() {
  /*
   * The console gate is the Supabase session itself - not a local flag.
   * `isSignedIn` is derived from the session object the library restores and
   * keeps refreshed, so there is no boolean here for anyone to flip.
   */
  const { isSignedIn, isResolving, user, signIn, signUp, signOut } = useAuth()

  /*
   * Which access screen the user has opened, if any. `null` keeps them on the
   * intro. The access screen appears only on an explicit Sign In / Register -
   * never automatically when the clip ends - and leaving it (Back) returns
   * here. `isResolving` is deliberately not gated on: the controls are live from
   * the first frame, whether or not the stored session has been read yet.
   */
  const [authView, setAuthView] = useState(null) // null | 'login' | 'register'

  // A live session is the gate. Once signed in, the dashboard is the whole
  // screen and both the intro and the access screen are gone.
  if (isSignedIn) {
    return <Console user={user} onSignOut={signOut} />
  }

  // The user chose Sign In or Register. Back returns to the intro, which
  // remounts and restarts the clip cleanly.
  if (authView) {
    return (
      <AuthPage
        initialMode={authView}
        onSignIn={signIn}
        onSignUp={signUp}
        onBack={() => setAuthView(null)}
      />
    )
  }

  // Default: the looping intro hero, with the access controls above it and
  // clickable at any point in the animation.
  return (
    <>
      <GridoptIntro />
      <IntroAuthBar
        onSignIn={() => setAuthView('login')}
        onRegister={() => setAuthView('register')}
      />
    </>
  )
}

function Console({ user, onSignOut }) {
  const { status, stations, network, error, reload } = useNetwork()
  const optimization = useOptimization()

  const [start, setStart] = useState(null)
  const [view, setView] = useState('network')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerTab, setDrawerTab] = useState('routes')

  // Default to the busiest hub so the panel is runnable the moment it loads.
  useEffect(() => {
    if (start || stations.length === 0) return
    const busiest = [...stations].sort((a, b) => b.connections - a.connections)[0]
    setStart(busiest?.name ?? stations[0].name)
  }, [stations, start])

  /*
   * Changing the origin invalidates the run that is on screen. Clearing it
   * keeps the panel honest: the results, the drawn route and the origin marker
   * always describe the same station, never a mix of the old run and the new
   * selection.
   */
  const chooseStart = (name) => {
    if (name === start) return
    if (optimization.status !== 'idle') optimization.reset()
    setStart(name)
  }

  const result = optimization.result
  const classical = result?.classical ?? optimization.classicalPreview
  const quantum = result?.hybrid

  const disabledViews = useMemo(() => {
    const blocked = []
    if (!classical) blocked.push('classical')
    if (!quantum) blocked.push('quantum', 'compare')
    return blocked
  }, [classical, quantum])

  // A finished run has something to show, so the canvas moves to it.
  useEffect(() => {
    if (optimization.status === 'success') setView('compare')
  }, [optimization.status])

  useEffect(() => {
    if (disabledViews.includes(view)) setView('network')
  }, [disabledViews, view])

  /*
   * What the selected depth will actually ask the simulator for. Used by the
   * sampling panel so its caption states the real configuration rather than a
   * decorative number.
   */
  const qaoaConfig = useMemo(() => {
    const profile = RUN_PROFILES[optimization.profileId] ?? RUN_PROFILES.full
    const window = profile.options.window ?? 4
    return { qubits: window ** 2, shots: profile.options.shots ?? 2048 }
  }, [optimization.profileId])

  const summary = network?.summary
  const shownStart = start
  const datasetName = network?.dataset_path?.split(/[\\/]/).pop()

  return (
    <div className={`shell ${drawerOpen ? 'shell--drawer' : ''}`}>
      <Rail
        summary={summary}
        status={status}
        datasetName={datasetName}
        user={user}
        onSignOut={onSignOut}
      />

      <main className="shell__main">
        <ControlColumn
          stations={stations}
          start={start}
          onStartChange={chooseStart}
          optimization={optimization}
          ready={status === 'ready'}
          qaoa={qaoaConfig}
        />

        <NetworkCanvas
          status={status}
          stations={stations}
          lines={network?.transmission_lines ?? []}
          error={error}
          onRetry={reload}
          view={view}
          onViewChange={setView}
          disabledViews={disabledViews}
          classicalLegs={classical?.tour?.legs}
          quantumLegs={quantum?.tour?.legs}
          start={shownStart}
          onSelectStation={chooseStart}
          locked={optimization.isRunning}
        />

        <ResultsColumn
          classical={classical}
          quantum={quantum}
          comparison={result?.comparison}
          energy={result?.energy}
          running={optimization.isRunning}
          totalStations={summary?.stations ?? 26}
        />
      </main>

      <Drawer
        open={drawerOpen}
        tab={drawerTab}
        onTabChange={setDrawerTab}
        onToggle={setDrawerOpen}
        badge={result ? `${result.classical.tour.stations_visited}` : null}
      >
        {drawerTab === 'routes' && <RoutesPanel result={result} />}
        {drawerTab === 'energy' && (
          <EnergyPanel network={network} energy={result?.energy} />
        )}
        {drawerTab === 'figures' && (
          <FiguresPanel
            available={Boolean(result?.graphs?.comparison)}
            cacheKey={optimization.finishedAt}
          />
        )}
        {drawerTab === 'method' && (
          <MethodPanel
            comparison={result?.comparison}
            quantumDetail={quantum?.detail}
            network={network}
          />
        )}
        {/* The assistant reads the same `result` the panels above render, so
            what it answers about and what the dashboard shows are the same
            run. With no run loaded it simply has no solver context, and says
            so rather than describing one. */}
        {drawerTab === 'assistant' && <AssistantPanel run={result} />}
      </Drawer>
    </div>
  )
}
