/**
 * The Supabase browser client - the authentication backend.
 *
 * `hooks/useAuth.js` registers, signs in and signs out through this client, and
 * `api/client.js` reads the current access token from it to authorize backend
 * requests. There is no second account store: sign-in is Supabase Auth, and
 * the user rows live in the project's Authentication -> Users table.
 *
 * ---------------------------------------------------------------------------
 *
 * WHICH KEY THIS USES
 *
 * The public key only, read from the environment under either of the two names
 * Supabase has used for it:
 *
 *     VITE_SUPABASE_ANON_KEY          (the name in Supabase's current docs)
 *     VITE_SUPABASE_PUBLISHABLE_KEY   (the newer name, and what this project's
 *                                      .env already holds)
 *
 * Both are the same public credential, so either satisfies this module and
 * neither is a secret: anything VITE_-prefixed is compiled into the bundle and
 * served to every visitor. That is by design here - the key carries no
 * authority of its own. What a caller may read or write is decided by Row
 * Level Security and table grants in the database, never by holding this key.
 *
 * The SERVICE-ROLE key bypasses RLS. It is never referenced here, never
 * referenced anywhere under src/, and must never be put in a VITE_ variable.
 * The guard at the bottom of this file refuses to start if one appears.
 *
 * SESSION HANDLING is left to the library: it persists the session, refreshes
 * the access token before it expires, and notifies `onAuthStateChange`
 * subscribers. That is what keeps a page reload signed in.
 */

import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const publicKey =
  import.meta.env.VITE_SUPABASE_ANON_KEY ??
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

/**
 * Whether the app was built with Supabase credentials at all.
 *
 * A missing value is a configuration mistake, not a runtime condition to paper
 * over, so the UI reports it plainly instead of failing with an opaque network
 * error on the first sign-in attempt.
 */
export const isSupabaseConfigured = Boolean(url && publicKey)

if (!isSupabaseConfigured) {
  // Names only. A value is never logged from this module.
  console.error(
    '[supabase] VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY (or ' +
      'VITE_SUPABASE_PUBLISHABLE_KEY) are not set. Copy frontend/.env.example ' +
      'to frontend/.env and fill them in, then restart the dev server.',
  )
}

/*
 * A guard against the worst possible configuration mistake. A secret key in a
 * VITE_ variable would be compiled into this bundle and served to every
 * visitor, handing them a credential that bypasses every policy in the
 * database. Refuse to run rather than ship that.
 */
if (publicKey && (publicKey.startsWith('sb_secret_') || publicKey.includes('service_role'))) {
  throw new Error(
    '[supabase] A SECRET key is set where the public key belongs. It would be ' +
      'published in the browser bundle. Use the anon/publishable key instead, ' +
      'and rotate the exposed secret immediately.',
  )
}

export const supabase = isSupabaseConfigured
  ? createClient(url, publicKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null
