/**
 * GRIDOPT access screen.
 *
 * Built to the supplied reference: a dark navy card outlined in glowing cyan,
 * split by a diagonal into a form half and a teal gradient panel. The panel
 * sweeps across the whole card and lands on the opposite side when the user
 * switches between signing in and registering, with the form swapping behind
 * it at the midpoint.
 *
 * The reference's palette, proportions, centred headings, underline fields with
 * trailing glyphs, glossy pill button and stacked switch prompt are all kept.
 * GRIDOPT supplies the wordmark and the copy; nothing else is invented.
 *
 * Authentication runs against Supabase Auth through `useAuth`. This screen
 * collects an email and a password and hands them over; it never compares a
 * credential itself and never decides on its own that a sign-in succeeded.
 * Passwords go straight to Supabase over TLS, are never stored by GRIDOPT, and
 * are never logged, displayed, or placed in a URL.
 *
 * Login takes an email rather than a username because Supabase accounts are
 * keyed by email. Registration keeps its username field, which is stored as
 * auth user metadata (a label), not a credential.
 *
 * The design is unchanged: same card, same diagonal sweep, same fields, same
 * pill button. Only the submit path behind it is different.
 */

import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, CircleNotch, EnvelopeSimple, Eye, EyeSlash, Lock, User } from '@phosphor-icons/react'

import '@fontsource/poppins/400.css'
import '@fontsource/poppins/500.css'
import '@fontsource/poppins/600.css'
import '@fontsource/poppins/700.css'
import './AuthPage.css'

/* Half the sweep: panel covers the card, form swaps, panel lands. */
const SWEEP_MS = 430

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const COPY = {
  login: {
    heading: 'Login',
    action: 'Login',
    welcome: ['Welcome', 'Back!'],
    switchPrompt: "Don't have an account?",
    switchAction: 'Sign Up',
  },
  register: {
    heading: 'Register',
    action: 'Register',
    welcome: ['Welcome!'],
    switchPrompt: 'Already have an account?',
    switchAction: 'Sign In',
  },
}

/**
 * Supabase's message, in the user's terms.
 *
 * Every failure the sign-in and sign-up calls can return, mapped to one plain
 * sentence. The wording for a bad sign-in stays deliberately vague about
 * *which* half was wrong: saying "no such account" would confirm to anyone
 * asking which addresses are registered here. Supabase already obscures that
 * for sign-in ("Invalid login credentials"); this mapping keeps the intent.
 *
 * Supabase reports a duplicate sign-up as "User already registered", a bad
 * address as "Unable to validate email address", a short password with its own
 * rule, and a throttled attempt as a rate limit. A dead network or a project
 * that is down never reaches Supabase at all and surfaces as a fetch failure -
 * different fix, different sentence.
 */
function describe(error) {
  const raw = (error?.message || '').toLowerCase()
  const status = error?.status

  if (raw.includes('invalid login') || raw.includes('incorrect')) {
    return 'Email or password is incorrect.'
  }
  if (raw.includes('already registered') || raw.includes('already exists')
      || raw.includes('user already')) {
    return 'An account already exists for this email. Sign in instead.'
  }
  if (raw.includes('email address') && (raw.includes('invalid') || raw.includes('validate'))) {
    return 'That email address is not valid. Check it and try again.'
  }
  if (raw.includes('email not confirmed')) {
    return 'Confirm your email from the link we sent, then sign in.'
  }
  if (raw.includes('password')) {
    // Supabase states its own rule, e.g. "Password should be at least 6 characters".
    return error.message
  }
  if (raw.includes('rate limit') || raw.includes('too many') || status === 429) {
    return 'Too many attempts. Wait a moment and try again.'
  }
  if (raw.includes('failed to fetch') || raw.includes('network')
      || raw.includes('load failed') || raw.includes('fetch failed')) {
    return 'Cannot reach the authentication service. Check your connection and try again.'
  }
  if (status >= 500) {
    return 'The authentication service is unavailable right now. Try again shortly.'
  }
  return error?.message || 'Something went wrong. Try again.'
}

export function AuthPage({ initialMode = 'login', onSignIn, onSignUp, onBack }) {
  // Which screen the user opened from the intro. Kept as the initial state only;
  // the in-card switch below still flips between the two from here.
  const [mode, setMode] = useState(initialMode === 'register' ? 'register' : 'login')
  const [sweeping, setSweeping] = useState(false)
  const [values, setValues] = useState({ username: '', email: '', password: '' })
  const [errors, setErrors] = useState({})
  const [reveal, setReveal] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // Form-level outcome: a rejected sign-in, or the confirm-your-email notice.
  const [alert, setAlert] = useState(null)
  const timers = useRef([])

  useEffect(() => () => timers.current.forEach(window.clearTimeout), [])

  const copy = COPY[mode]

  const change = (field) => (event) => {
    setValues((current) => ({ ...current, [field]: event.target.value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    setAlert(null)
  }

  const switchMode = () => {
    if (sweeping) return
    setSweeping(true)
    setErrors({})
    setAlert(null)
    timers.current.push(
      window.setTimeout(() => {
        setMode((current) => (current === 'login' ? 'register' : 'login'))
        setReveal(false)
        setSweeping(false)
      }, SWEEP_MS),
    )
  }

  /*
   * Shape checks only, to catch obvious typos before a round trip. They are
   * not the authority on anything: Supabase decides whether the credentials
   * are valid, and a sign-in is never granted on the strength of these.
   *
   * Sign-in deliberately does not impose a minimum password length. The rule
   * belongs to whatever the account was created with, and enforcing one here
   * would lock out a valid password rather than let the server reject it.
   */
  const validate = () => {
    const found = {}
    const email = values.email.trim()

    if (!EMAIL_PATTERN.test(email)) found.email = 'Enter a valid email address.'

    if (mode === 'register') {
      if (values.username.trim().length < 3) found.username = 'At least 3 characters.'
      if (values.password.length < 8) found.password = 'At least 8 characters.'
    } else if (values.password.length === 0) {
      found.password = 'Enter your password.'
    }

    return found
  }

  const submit = async (event) => {
    event.preventDefault()
    setAlert(null)

    const found = validate()
    setErrors(found)
    if (Object.keys(found).length > 0) return

    const email = values.email.trim()
    setSubmitting(true)

    try {
      if (mode === 'register') {
        const { error, needsConfirmation } = await onSignUp({
          email,
          password: values.password,
          username: values.username.trim(),
        })
        if (error) {
          setAlert({ tone: 'bad', text: describe(error) })
          return
        }
        if (needsConfirmation) {
          /*
           * Only reachable if this Supabase project turns email confirmation
           * back on: sign-up then creates the user but returns no session
           * until the emailed link is followed. Say so plainly rather than
           * leaving the user on a form that looks like it did nothing.
           */
          setAlert({
            tone: 'ok',
            text: `Account created. Confirm ${email} from the link we sent, then sign in.`,
          })
          setValues((current) => ({ ...current, password: '' }))
          return
        }
        // With confirmation off, sign-up returns a session and the auth state
        // subscription swaps this screen for the console on its own.
        return
      }

      const { error } = await onSignIn({ email, password: values.password })
      if (error) setAlert({ tone: 'bad', text: describe(error) })
      // On success the session arrives through the store subscription; this
      // component unmounts. Nothing to do here.
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth">
      <div className="auth__glow" aria-hidden="true" />

      {onBack && (
        <button type="button" className="auth__back" onClick={onBack}>
          <ArrowLeft size={15} weight="bold" />
          Back
        </button>
      )}

      <main className={`auth__card auth__card--${mode} ${sweeping ? 'is-sweeping' : ''}`}>
        {/* --- the sweeping panel ----------------------------------------- */}
        <div className="auth__panel" aria-hidden="true">
          <span className="auth__facet" />
          <div className="auth__panelinner">
            <span className="auth__mark">GRIDOPT</span>
            <p className="auth__welcome">
              {copy.welcome.map((line) => (
                <span key={line}>{line}</span>
              ))}
            </p>
            <span className="auth__rule" />
            <p className="auth__tag">Hybrid quantum-classical grid optimization</p>
          </div>
        </div>

        {/* --- the form ---------------------------------------------------- */}
        <section className="auth__side">
          <form className="auth__form" onSubmit={submit} noValidate>
            <h1 className="auth__title">{copy.heading}</h1>

            {/*
              Registration keeps its username field; the name is a label stored
              on the auth user, never a credential. Sign-in has no use for it:
              the account store is keyed by email, so the first field is the
              email in that mode and the card keeps its two-field shape.
            */}
            {mode === 'register' && (
              <Field
                id="username"
                label="Username"
                icon={<User size={16} weight="fill" />}
                value={values.username}
                onChange={change('username')}
                error={errors.username}
                autoComplete="username"
              />
            )}

            <Field
              id="email"
              label="Email"
              type="email"
              icon={<EnvelopeSimple size={16} weight="fill" />}
              value={values.email}
              onChange={change('email')}
              error={errors.email}
              autoComplete="email"
            />

            <Field
              id="password"
              label="Password"
              type={reveal ? 'text' : 'password'}
              icon={
                <button
                  type="button"
                  className="auth__peek"
                  onClick={() => setReveal((v) => !v)}
                  aria-label={reveal ? 'Hide password' : 'Show password'}
                  tabIndex={-1}
                >
                  {reveal ? <EyeSlash size={16} weight="fill" /> : <Lock size={16} weight="fill" />}
                </button>
              }
              value={values.password}
              onChange={change('password')}
              error={errors.password}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />

            {alert && (
              <p className={`auth__alert auth__alert--${alert.tone}`} role="alert">
                {alert.text}
              </p>
            )}

            <button type="submit" className="auth__submit" disabled={submitting}>
              {submitting && <CircleNotch size={15} weight="bold" className="auth__spin" />}
              {submitting ? 'Opening console' : copy.action}
            </button>

            <p className="auth__switch">
              {copy.switchPrompt}
              <button type="button" onClick={switchMode} disabled={sweeping}>
                {copy.switchAction}
              </button>
            </p>
          </form>

          <p className="auth__note">
            Secured by Supabase Auth. GRIDOPT never stores your password.
          </p>
        </section>
      </main>
    </div>
  )
}

/** Label and glyph on one row, the input riding an underline beneath it. */
function Field({ id, label, icon, error, type = 'text', ...rest }) {
  return (
    <div className={`field ${error ? 'is-bad' : ''}`}>
      <div className="field__head">
        <label className="field__label" htmlFor={id}>
          {label}
        </label>
        <span className="field__icon">{icon}</span>
      </div>
      <input id={id} type={type} className="field__input" spellCheck="false" {...rest} />
      <span className="field__error">{error ?? ''}</span>
    </div>
  )
}
