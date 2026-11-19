import { useEffect, useState } from 'react'
import { listDocuments, summarise } from '../api/client.js'
import Markdown from '../components/Markdown.jsx'
import Accordion from '../components/ui/Accordion.jsx'
import Button from '../components/ui/Button.jsx'
import Checkbox from '../components/ui/Checkbox.jsx'
import NumberInput from '../components/ui/NumberInput.jsx'
import { BackendSelect, ErrorBox, KeyValues, PageHeader, Spinner } from '../components/common.jsx'

const MAX_DOCUMENTS = 20

export default function Summarise() {
  const [docs, setDocs] = useState([])
  const [loadingDocs, setLoadingDocs] = useState(true)
  const [selected, setSelected] = useState(new Set())
  const [backend, setBackend] = useState('hosted')
  const [concurrency, setConcurrency] = useState(4)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    listDocuments(100, 0)
      .then((d) => setDocs(d.items))
      .catch(setError)
      .finally(() => setLoadingDocs(false))
  }, [])

  function toggle(id) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else if (next.size < MAX_DOCUMENTS) next.add(id)
    setSelected(next)
  }

  async function run() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await summarise([...selected], backend, Number(concurrency)))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const m = result?.meta
  return (
    <>
      <PageHeader title="Summarise">
        Pick up to {MAX_DOCUMENTS} documents. Each is summarised in parallel (a few at a time), then
        one call combines the summaries. A document that fails is retried once and reported.
      </PageHeader>

      <div className="card">
        {loadingDocs ? (
          <Spinner label="Loading documents…" />
        ) : docs.length === 0 ? (
          <p className="muted">No documents yet. Upload some on the Documents page first.</p>
        ) : (
          <ul className="checklist">
            {docs.map((d) => (
              <li key={d.id}>
                <Checkbox checked={selected.has(d.id)} onChange={() => toggle(d.id)}>
                  <span>{d.title}</span> <span className="muted small">{d.source}</span>
                </Checkbox>
              </li>
            ))}
          </ul>
        )}
        <div className="row">
          <div className="inline">
            Model <BackendSelect value={backend} onChange={setBackend} />
          </div>
          <div className="inline">
            At most
            <NumberInput value={concurrency} onChange={setConcurrency} min={1} max={8} aria-label="Calls at once" />
            calls at once
          </div>
        </div>
        <div className="row between action-row">
          <span className="muted">{selected.size} of {MAX_DOCUMENTS} selected</span>
          <Button variant="primary" icon="summarise" onClick={run} loading={busy} disabled={selected.size === 0}>
            {busy ? 'Summarising…' : 'Summarise'}
          </Button>
        </div>
      </div>

      <ErrorBox error={error} />

      {result && (
        <>
          <div className="card">
            <h2>Overview</h2>
            <Markdown>{result.overview}</Markdown>
            {result.failed.length > 0 && (
              <div className="warning">
                <strong>{m.coverage}</strong>
                <ul>
                  {result.failed.map((f) => (
                    <li key={f.document_id}>
                      {f.title}: {f.error} after {f.attempts} attempts
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="card">
            <h2>Summaries</h2>
            {result.summaries.map((s) => (
              <Accordion key={s.document_id} title={s.title}>
                <Markdown>{s.summary}</Markdown>
              </Accordion>
            ))}
          </div>

          <div className="card">
            <h2>Details</h2>
            <KeyValues
              rows={[
                ['coverage', m.coverage],
                ['model calls', m.model_calls],
                ['most calls at once', `${m.peak_in_flight} (limit ${m.concurrency})`],
                ['summaries took', `${m.map_seconds} s`],
                ['combine took', `${m.combine_seconds} s`],
                ['tokens (in / out)', `${m.input_tokens} / ${m.output_tokens}`],
              ]}
            />
          </div>
        </>
      )}
    </>
  )
}
