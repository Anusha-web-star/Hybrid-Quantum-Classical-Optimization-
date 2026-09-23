/**
 * The access controls over the intro hero.
 *
 * Two subtle buttons in the top-right corner, live from the first frame and
 * sitting above the looping animation so they can be clicked at any point in it.
 * They do not gate the intro or interrupt it: pressing one opens the existing
 * access screen (`AuthPage`) in the matching mode; doing nothing leaves the clip
 * looping. This bar carries no auth logic of its own - it only reports which
 * screen the user asked for.
 *
 * It is a sibling of the (decorative, aria-hidden) intro layer rather than a
 * child of it, so the buttons stay in the accessibility tree and reachable by
 * keyboard while the video itself is hidden from it.
 */

import { SignIn, UserPlus } from '@phosphor-icons/react'

import './IntroAuthBar.css'

export function IntroAuthBar({ onSignIn, onRegister }) {
  return (
    <nav className="introauth" aria-label="Account">
      <button type="button" className="introauth__btn" onClick={onSignIn}>
        <SignIn size={15} weight="bold" />
        Sign In
      </button>
      <button
        type="button"
        className="introauth__btn introauth__btn--primary"
        onClick={onRegister}
      >
        <UserPlus size={15} weight="bold" />
        Register
      </button>
    </nav>
  )
}
