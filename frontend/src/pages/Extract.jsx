import { useState } from 'react'
import { extract } from '../api/client.js'
import Button from '../components/ui/Button.jsx'
import { BackendSelect, ErrorBox, KeyValues, PageHeader } from '../components/common.jsx'

const SAMPLES = [
  'hi, mera naam Rohan Mehta hai, Surat se. Data science course ke baare me janna tha, budget 50k tak hai. jaldi batao, kal tak. 98765 43210',
  'Hello, I am Priya from Ahmedabad (priya.shah@example.com). Interested in the MERN course starting next month. Is there an EMI option? Budget around 40,000.',
  'asdf qwerty 123',
]

export default function Extract() {
  const [text, setText] = useState(SAMPLES[0])
  const [backend, setBackend] = useState('hosted')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function run(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await extract(text, backend))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Extract">
        Turn a messy student enquiry into clean fields. A value the text does not contain comes back
        as null, never guessed.
      </PageHeader>

      <form className="card" onSubmit={run}>
        <label>
          Enquiry text
          <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} maxLength={8000} />
        </label>
        <div className="row">
          <span className="muted">Samples:</span>
          {SAMPLES.map((s, i) => (
            <button type="button" className="link" key={i} onClick={() => setText(s)}>
              {i + 1}
            </button>
          ))}
          <span className="grow" />
          <div className="inline">
            Model <BackendSelect value={backend} onChange={setBackend} />
          </div>
          <Button type="submit" variant="primary" icon="extract" loading={busy} disabled={!text.trim()}>
            Extract
          </Button>
        </div>
      </form>

      <ErrorBox error={error} />

      {result && (
        <div className="grid2">
          <div className="card">
            <h2>Extracted data</h2>
            <KeyValues rows={Object.entries(result.data)} />
          </div>
          <div className="card">
            <h2>How it went</h2>
            <KeyValues
              rows={[
                ['backend', result.meta.backend],
                ['model', result.meta.model],
                ['latency', `${result.meta.latency_ms} ms`],
                ['attempts', result.meta.attempts],
                ['fallback used', result.meta.fallback_used ? 'yes' : 'no'],
                ['input tokens', result.meta.input_tokens],
                ['output tokens', result.meta.output_tokens],
                ['cached input tokens', result.meta.cache_read_tokens],
              ]}
            />
            {result.meta.attempts > 1 && (
              <p className="muted small">
                The first reply was not valid, so the model was shown its mistake and asked again.
              </p>
            )}
          </div>
        </div>
      )}
    </>
  )
}
