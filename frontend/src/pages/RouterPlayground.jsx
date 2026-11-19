import { useState } from 'react'
import { route } from '../api/client.js'
import Markdown from '../components/Markdown.jsx'
import Button from '../components/ui/Button.jsx'
import { BackendSelect, ErrorBox, KeyValues, PageHeader } from '../components/common.jsx'

const SAMPLES = [
  'How much is the Python course?',
  'I was charged twice for my course',
  'When does the next weekend batch start?',
  'My laptop is broken, I missed three classes, and I also want a refund',
]

export default function RouterPlayground() {
  const [message, setMessage] = useState(SAMPLES[0])
  const [small, setSmall] = useState('hosted')
  const [large, setLarge] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function run(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await route(message, small, large || undefined))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const m = result?.meta
  return (
    <>
      <PageHeader title="Router">
        A rule or a small model decides the intent, then a specialised prompt answers. An unclear
        request goes to the large model.
      </PageHeader>

      <form className="card" onSubmit={run}>
        <label>
          Message
          <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={4000} />
        </label>
        <div className="row">
          <span className="muted">Samples:</span>
          {SAMPLES.map((s, i) => (
            <button type="button" className="link" key={i} onClick={() => setMessage(s)}>
              {i + 1}
            </button>
          ))}
        </div>
        <div className="row">
          <div className="inline">
            Small model <BackendSelect value={small} onChange={setSmall} />
          </div>
          <div className="inline">
            Large model{' '}
            <BackendSelect value={large} onChange={setLarge} allowDefault defaultLabel="server default" />
          </div>
          <span className="grow" />
          <Button type="submit" variant="primary" icon="route" loading={busy} disabled={!message.trim()}>
            Route
          </Button>
        </div>
      </form>

      <ErrorBox error={error} />

      {result && (
        <>
          <div className="card">
            <div className="row">
              <span className={`badge intent-${m.intent}`}>{m.intent}</span>
              <span className="muted">
                {m.rule_matched ? 'decided by a rule (no model call)' : 'decided by the small model'}
              </span>
            </div>
            <h2>Answer</h2>
            <Markdown>{result.answer}</Markdown>
          </div>
          <div className="card">
            <h2>Details</h2>
            <KeyValues
              rows={[
                ['answered by', `${m.answer_backend} / ${m.answer_model}`],
                ['classify time', `${m.classify_latency_ms} ms`],
                ['answer time', `${m.answer_latency_ms} ms`],
                ['total time', `${m.total_latency_ms} ms`],
                ['classify tokens (in / out)', `${m.classify_input_tokens ?? '-'} / ${m.classify_output_tokens ?? '-'}`],
                ['answer tokens (in / out)', `${m.answer_input_tokens ?? '-'} / ${m.answer_output_tokens ?? '-'}`],
              ]}
            />
          </div>
        </>
      )}
    </>
  )
}
