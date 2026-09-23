/**
 * The signed-in session, and the three things you can do to it.
 *
 * Backed by Supabase Auth. Sign-up, sign-in and sign-out are real network calls
 * to the project's GoTrue service; credentials are managed by Supabase, not by
 * this application, and no password is ever stored by GRIDOPT or written to
 * browser storage. The browser holds only the public key and the session the
 * service returns.
 *
 * The Supabase session is the single source of truth for "is anyone signed in".
 * There is no local boolean to flip: `status` and `isSignedIn` are derived from
 * the session object the library restores from storage and keeps fresh. On a
 * page reload the library re-reads the persisted session and refreshes the
 * access token before it expires, which is what keeps a refresh inside the
 * console. `onAuthStateChange` delivers SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED
 * and INITIAL_SESSION, including events raised in another tab, and every one of
 * them is applied from the session the event carries rather than from a guess
 * about what the event implies.
 *
 * The returned shape is unchanged, so `App.jsx`, `AuthPage.jsx` and `Rail.jsx`
 * consume `status`, `isSignedIn`, `user`, `signIn`, `signUp` and `signOut`
 * exactly as before: the mechanism changed underneath, the screens did not.
 *
 *   'loading'   - the stored session has not been read yet. Rendering the login
 *                 page here would flash it at somebody already signed in.
 *   'signedIn'  - there is a live session.
 *   'signedOut' - there is definitively none.
 */

import { useCallback, useEffect, useState } from 'react'

import { isSupabaseConfigured, supabase } from '../lib/supabase.js'

/** The one message shown when the app was built with no Supabase credentials. */
const NOT_CONFIGURED = {
  message:
    'Authentication is not configured in this build. Set VITE_SUPABASE_URL and ' +
    'VITE_SUPABASE_ANON_KEY in frontend/.env and restart.',
}

export function useAuth() {
  const [session, setSession] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    // A build with no Supabase credentials cannot sign anyone in. Resolve to a
    // usable signed-out app rather than hanging on 'loading' forever; the
    // client module has already logged the misconfiguration to the console.
    if (!isSupabaseConfigured) {
      setStatus('signedOut')
      return undefined
    }

    let active = true

    const apply = (next) => {
      if (!active) return
      setSession(next ?? null)
      setStatus(next ? 'signedIn' : 'signedOut')
    }

    // Restore whatever session is persisted before the first render decision.
    supabase.auth
      .getSession()
      .then(({ data }) => apply(data.session))
      .catch(() => apply(null))

    /*
     * Later changes. SIGNED_IN and TOKEN_REFRESHED both arrive with a session
     * and are applied the same way - a refreshed token must replace the stored
     * one, or `api/client.js` would keep sending the expired access token until
     * the next reload. SIGNED_OUT arrives with none. Events raised in another
     * tab come through here too, so signing out once signs out everywhere.
     */
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      apply(next)
    })

    return () => {
      active = false
      data.subscription.unsubscribe()
    }
  }, [])

  /** Sign in with an existing account. Returns `{ error }`, never throws. */
  const signIn = useCallback(async ({ email, password }) => {
    if (!supabase) return { error: NOT_CONFIGURED }
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    // On success the session arrives through onAuthStateChange; nothing else
    // to do here.
    return { error: error ?? null }
  }, [])

  /**
   * Create an account.
   *
   * `username` is passed as `options.data`, which Supabase stores on the auth
   * user as `user_metadata`. It is a label the console shows, never a
   * credential and never used to authenticate.
   *
   * With email confirmation OFF - how this project's Supabase is configured -
   * sign-up returns a session immediately and `onAuthStateChange` swaps in the
   * console on its own. If confirmation is ever turned back on, Supabase
   * creates the user but returns no session; that is surfaced as
   * `needsConfirmation` so the form can say to check the mailbox instead of
   * appearing to do nothing.
   */
  const signUp = useCallback(async ({ email, password, username }) => {
    if (!supabase) return { error: NOT_CONFIGURED }
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { username } },
    })
    if (error) return { error }
    return { error: null, needsConfirmation: !data.session }
  }, [])

  /** Sign out and clear the persisted session. */
  const signOut = useCallback(async () => {
    if (!supabase) return { error: null }
    const { error } = await supabase.auth.signOut()
    return { error: error ?? null }
  }, [])

  return {
    session,
    user: session?.user ?? null,
    status,
    isSignedIn: status === 'signedIn',
    isResolving: status === 'loading',
    signIn,
    signUp,
    signOut,
  }
}
