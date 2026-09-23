/**
 * The assistant panel.
 *
 * It lives in the drawer alongside Routes, Energy and Method, at the same
 * weight as they are. This is deliberately not a chat application: it is one
 * more instrument on the panel, reading the same run everything else reads.
 *
 * What it shows, and why each part is there:
 *
 *   - the answer, and nothing before it. While a question is in flight the
 *     panel shows the question and a working state; it never renders provisional
 *     answer text, because a placeholder that later changes is indistinguishable
 *     from a fabricated one.
 *   - the sources, always. Every answer carries the context it was built from -
 *     a CSV row, a document heading, a field of the current run - so a figure
 *     can be checked rather than trusted.
 *   - an explicit "not answered" state. When the backend reports
 *     `grounded: false` the reply is the project's unavailable line, and it is
 *     styled as a gap in the data rather than as a result. A missing model
 *     credential is a different thing entirely and arrives as a 503, so it is
 *     shown as a configuration error rather than as an empty answer.
 */

import { useEffect, useRef, useState } from 'react'
import {
  ArrowUp, Broom, Code, Database, FileText, Path, WarningCircle,
} from '@phosphor-icons/react'

import { EXAMPLE_QUESTIONS, useAssistant } from '../../hooks/useAssistant.js'
import './AssistantPanel.css'

/** One icon and one label per source family, matching the backend's `kind`. */
const KINDS = {
  dataset: { icon: Database, label: 'dataset' },
  doc: { icon: FileText, label: 'docs' },
  code: { icon: Code, label: 'source code' },
  solver: { icon: Path, label: 'this run' },
}

export function AssistantPanel({ run }) {
  const assistant = useAssistant(run)
  const [draft, setDraft] = useState('')
  const endRef = useRef(null)

  // Keep the newest exchange in view as the transcript grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [assistant.turns.length, assistant.status])

  const submit = (event) => {
    event.preventDefault()
    if (assistant.isAsking) return
    const question = draft.trim()
    if (!question) return
    setDraft('')
    assistant.ask(question)
  }

  const examples = EXAMPLE_QUESTIONS.filter(
    (example) => !example.needsRun || assistant.hasRun,
  )

  return (
    <section className="asst">
      <header className="asst__head">
        <div>
          <p className="asst__title">Project assistant</p>
          <p className="asst__sub">
            Answers from this project&apos;s dataset, documentation, source code and
            {assistant.hasRun ? ' the run on screen' : ' — no run loaded yet'}.
            Nothing outside it.
          </p>
        </div>
        {assistant.turns.length > 0 && (
          <button type="button" className="asst__clear" onClick={assistant.clear}>
            <Broom size={12} weight="bold" />
            Clear
          </button>
        )}
      </header>

      <div className="asst__thread">
        {assistant.turns.length === 0 && !assistant.isAsking && (
          <p className="asst__empty">
            Ask about a transmission line, the loss-cost basis, the methodology,
            or the routes this run produced.
          </p>
        )}

        {assistant.turns.map((turn) => (
          <Turn key={turn.id} turn={turn} />
        ))}

        {assistant.isAsking && (
          <Pending question={assistant.pending} elapsedMs={assistant.elapsedMs} />
        )}

        {assistant.status === 'error' && (
          <Failure error={assistant.error} onDismiss={assistant.dismissError} />
        )}

        <div ref={endRef} />
      </div>

      {examples.length > 0 && (
        <div className="asst__examples">
          {examples.map((example) => (
            <button
              key={example.text}
              type="button"
              className="asst__chip"
              disabled={assistant.isAsking}
              onClick={() => assistant.ask(example.text)}
            >
              {example.text}
            </button>
          ))}
        </div>
      )}

      <form className="asst__form" onSubmit={submit}>
        <input
          type="text"
          className="asst__input"
          value={draft}
          maxLength={2000}
          placeholder="Ask about the network, a route, or the method"
          aria-label="Ask the GRIDOPT project assistant"
          onChange={(event) => setDraft(event.target.value)}
          disabled={assistant.isAsking}
        />
        <button
          type="submit"
          className="asst__send"
          disabled={assistant.isAsking || !draft.trim()}
          aria-label="Send question"
        >
          <ArrowUp size={13} weight="bold" />
        </button>
      </form>
    </section>
  )
}

function Turn({ turn }) {
  return (
    <article className="asst__turn">
      <p className="asst__q">{turn.question}</p>

      <div className={`asst__a ${turn.grounded ? '' : 'is-ungrounded'}`}>
        {/* The only ungrounded answer that reaches this component is a real
            gap in the project data. A missing model credential is a 503 and
            renders as a configuration error instead - see Failure below. */}
        {!turn.grounded && (
          <p className="asst__flag">
            <WarningCircle size={12} weight="fill" />
            Not in the available GRIDOPT data
          </p>
        )}
        <p className="asst__text">{turn.answer}</p>
      </div>

      {turn.sources.length > 0 && (
        <Sources sources={turn.sources} usedRun={turn.usedSolverContext} />
      )}
    </article>
  )
}

/**
 * The context the answer was built from.
 *
 * Collapsed by default so the panel stays compact, but never omitted: the
 * summary line states the count and the families before it is opened.
 */
function Sources({ sources, usedRun }) {
  const families = [...new Set(sources.map((source) => source.kind))]

  return (
    <details className="asst__sources">
      <summary className="asst__srcsum">
        {sources.length} source{sources.length === 1 ? '' : 's'}
        <span className="asst__srckinds">
          {families.map((kind) => {
            const family = KINDS[kind] ?? { icon: FileText, label: kind }
            const Icon = family.icon
            return (
              <span key={kind} className={`asst__kind asst__kind--${kind}`}>
                <Icon size={10} weight="bold" />
                {family.label}
              </span>
            )
          })}
        </span>
        {usedRun && <span className="asst__live mono">live run</span>}
      </summary>

      <ul className="asst__srclist">
        {sources.map((source) => (
          <li key={source.id} className="asst__src">
            <span className={`asst__dot asst__dot--${source.kind}`} aria-hidden="true" />
            <span className="asst__srctitle">{source.title}</span>
            <span className="asst__srcloc mono">{source.locator}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}

/**
 * A question in flight. Carries no answer text - there isn't one yet.
 *
 * The label used to read "retrieving project context" for the whole wait, which
 * was simply false: retrieval finishes in well under a millisecond, and every
 * remaining second is the local model reading the prompt. Naming the wrong
 * stage made a working request look like a stuck one. It now names the stage
 * that is actually running and counts real elapsed seconds, so a long wait
 * reads as slow rather than broken.
 */
function Pending({ question, elapsedMs }) {
  const seconds = Math.floor(elapsedMs / 1000)

  return (
    <article className="asst__turn" aria-live="polite">
      <p className="asst__q">{question}</p>
      <p className="asst__working mono">
        <span className="asst__pulse" aria-hidden="true" />
        {seconds < 2 ? 'reading project context' : 'local model composing answer'}
        <span className="asst__clock">{seconds}s</span>
      </p>
      {seconds >= 20 && (
        <p className="asst__slow">
          The model runs on this machine&apos;s CPU, so most of this wait is it
          reading the retrieved context. Nothing is being sent anywhere.
        </p>
      )}
    </article>
  )
}

/**
 * A failure, told apart by cause.
 *
 * A missing model credential is a server configuration fault, not a gap in the
 * project data, and the panel says so in those words - including that retrieval
 * itself worked. Showing it as "no answer in the GRIDOPT data" would send the
 * reader hunting for a dataset row that is already there.
 */
function Failure({ error, onDismiss }) {
  const message = error?.message ?? 'The assistant could not answer.'
  const isConfig = error?.code === 'assistant_not_configured'
  const retrieved = error?.detail?.retrieved

  return (
    <div className="asst__error" role="alert">
      <WarningCircle size={15} weight="fill" />
      <div>
        <p className="asst__errtitle">
          {isConfig ? 'The assistant is not configured' : 'The assistant could not answer'}
        </p>
        <p className="asst__errmsg">{message}</p>

        {isConfig && (
          <>
            {retrieved > 0 && (
              <p className="asst__errmsg">
                Retrieval is working — this question matched {retrieved} project
                source{retrieved === 1 ? '' : 's'}. Only answer generation is unavailable.
              </p>
            )}
            {/* The fixing command comes from the backend rather than being
                written here: whether the local model runtime is stopped or the
                model simply is not pulled yet needs two different commands, and
                only the server knows which. */}
            {error?.detail?.hint && (
              <p className="asst__errcmd mono">{error.detail.hint}</p>
            )}
          </>
        )}

        {error?.code === 'network_unreachable' && (
          <p className="asst__errcmd mono">
            .venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
          </p>
        )}
      </div>
      <button type="button" className="asst__dismiss" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  )
}
