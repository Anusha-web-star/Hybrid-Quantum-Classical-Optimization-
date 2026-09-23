/**
 * The top rail.
 *
 * Identity on the left, live network facts in the middle, backend state on the
 * right. It replaces the old hero: the same information that used to occupy a
 * full screen of prose now sits in 52px, and the user reaches the controls
 * immediately.
 */

import { CircleNotch, Cube, SignOut, Warning } from '@phosphor-icons/react'

import './Rail.css'

export function Rail({ summary, status, datasetName, user, onSignOut }) {
  return (
    <header className="rail">
      <div className="rail__brand">
        <Cube size={19} weight="duotone" className="rail__mark" />
        <span className="rail__name">GRIDOPT</span>
        <span className="rail__what">
          Hybrid quantum-classical routing over the Karnataka transmission grid
        </span>
      </div>

      <div className="rail__facts">
        {summary ? (
          <>
            <Fact value={summary.stations} unit="stations" />
            <Fact value={summary.routable_lines} unit="lines" />
            <Fact
              value={Math.round(summary.total_line_km).toLocaleString('en-US')}
              unit="km total"
            />
            <Fact
              value={summary.connected ? 'connected' : 'split'}
              unit={`${summary.components} component${summary.components === 1 ? '' : 's'}`}
              text
            />
          </>
        ) : (
          <span className="rail__loading mono">reading dataset</span>
        )}
      </div>

      <div className="rail__right">
        {datasetName && <span className="rail__dataset mono">{datasetName}</span>}
        <Connection status={status} />
        {user && (
          <>
            <span className="rail__who mono" title={user.email}>
              {user.user_metadata?.username || user.email}
            </span>
            <button
              type="button"
              className="rail__signout"
              onClick={onSignOut}
              title="Sign out"
            >
              <SignOut size={13} weight="bold" />
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  )
}

function Fact({ value, unit, text = false }) {
  return (
    <span className="fact">
      <span className={`fact__v ${text ? 'fact__v--text' : 'num'}`}>{value}</span>
      <span className="fact__u">{unit}</span>
    </span>
  )
}

/**
 * The one live indicator on the page. It carries real backend state, which is
 * the only justification for a coloured dot.
 */
function Connection({ status }) {
  if (status === 'loading') {
    return (
      <span className="conn conn--wait">
        <CircleNotch size={12} weight="bold" className="conn__spin" />
        connecting
      </span>
    )
  }
  if (status === 'error') {
    return (
      <span className="conn conn--down">
        <Warning size={12} weight="fill" />
        api offline
      </span>
    )
  }
  return (
    <span className="conn conn--live">
      <span className="conn__dot" />
      api live
    </span>
  )
}
