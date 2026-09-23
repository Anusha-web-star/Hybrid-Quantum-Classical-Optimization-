/**
 * GRIDOPT intro.
 *
 * The standalone animation demo, played full-viewport as the hero of the access
 * screen. It is a layer, not a route: it covers the app while the user is signed
 * out and has not opened Sign In / Register. It plays, and when the clip ends it
 * loops - continuously - until the user acts. It never advances anywhere on its
 * own; the access controls above it (see `IntroAuthBar`) are the only way off it.
 *
 * One rule governs playback: a clip that can play should play. A decode failure,
 * a missing file or an autoplay refusal is not fatal here - there is nothing to
 * fall through to, because authentication is manual - so a failure simply leaves
 * the black hero in place, with the access controls still live above it.
 *
 * A rejected play() is not by itself a failure: the browser also rejects when a
 * pending request is superseded, which happens routinely on re-render and in
 * StrictMode's double mount. So a rejection is retried, and only its reason is
 * logged if it ultimately gives up. A healthy run logs nothing.
 */

import { useEffect, useRef } from 'react'

import './GridoptIntro.css'

const SOURCE = '/videos/gridopt-intro.mp4'

/* How many times a superseded play() request is re-issued before giving up. */
const PLAY_ATTEMPTS = 3

export function GridoptIntro() {
  const videoRef = useRef(null)

  /*
   * `autoPlay` covers the common case. Calling play() as well catches the tabs
   * that were restored or backgrounded during load, and hands us the rejection
   * to classify when playback does not begin.
   */
  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined

    let cancelled = false

    const start = (attempt) => {
      if (cancelled) return

      const started = video.play()
      if (!started?.catch) return

      started.catch((cause) => {
        if (cancelled) return

        // The element itself failed - decode, network, or no source at all.
        // Nothing to do but leave the black hero; the controls stay usable.
        if (video.error) {
          console.warn(`[GridoptIntro] media error ${video.error.code} (${video.error.message || 'no detail'})`)
          return
        }

        // The browser will not start playback without a gesture. Muted inline
        // video is exempt from that everywhere it matters, so this is rare.
        if (cause?.name === 'NotAllowedError') {
          console.warn('[GridoptIntro] autoplay refused by the browser')
          return
        }

        /*
         * Anything else - overwhelmingly AbortError, "interrupted by a new load
         * request" - means this particular request lost a race, not that the
         * clip is unplayable. Ask again on the next frame.
         */
        if (attempt < PLAY_ATTEMPTS) {
          window.requestAnimationFrame(() => start(attempt + 1))
          return
        }

        console.warn(`[GridoptIntro] play() kept failing (${cause?.name || 'unknown'}: ${cause?.message || ''})`)
      })
    }

    start(1)

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="intro" aria-hidden="true">
      <video
        ref={videoRef}
        className="intro__video"
        src={SOURCE}
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        disablePictureInPicture
      />
    </div>
  )
}
