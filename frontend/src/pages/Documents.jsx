import { useCallback, useEffect, useState } from 'react'
import { deleteDocument, getDocument, listDocuments, uploadDocument } from '../api/client.js'
import { ErrorBox, PageHeader, Spinner, formatDate } from '../components/common.jsx'
import Button from '../components/ui/Button.jsx'
import { useConfirm } from '../components/ui/Confirm.jsx'
import FileInput from '../components/ui/FileInput.jsx'

const PAGE_SIZE = 20

export default function Documents() {
  const confirm = useConfirm()
  const [data, setData] = useState({ items: [], total: 0 })
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [uploading, setUploading] = useState(false)
  const [viewing, setViewing] = useState(null) // a document with its text

  const load = useCallback(() => {
    setLoading(true)
    listDocuments(PAGE_SIZE, offset)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [offset])
  useEffect(load, [load])

  async function upload(e) {
    e.preventDefault()
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      await uploadDocument(file, title.trim())
      setFile(null)
      setTitle('')
      if (offset === 0) load()
      else setOffset(0)
    } catch (err) {
      setError(err)
    } finally {
      setUploading(false)
    }
  }

  async function view(id) {
    setError(null)
    try {
      setViewing(await getDocument(id))
    } catch (err) {
      setError(err)
    }
  }

  async function remove(doc) {
    const ok = await confirm({
      title: 'Delete this document?',
      message: `“${doc.title}” will be removed for good.`,
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    try {
      await deleteDocument(doc.id)
      if (viewing?.id === doc.id) setViewing(null)
      load()
    } catch (err) {
      setError(err)
    }
  }

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE))
  const page = Math.floor(offset / PAGE_SIZE) + 1

  return (
    <>
      <PageHeader title="Documents">
        Upload .txt, .md or .pdf files (up to 20 MB). They are private to your organisation.
      </PageHeader>

      <form className="card upload" onSubmit={upload}>
        <FileInput file={file} onChange={setFile} accept=".txt,.md,.pdf" hint=".txt, .md or .pdf, up to 20 MB" />
        <div className="row">
          <input
            className="grow"
            placeholder="Title (optional)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={255}
          />
          <Button type="submit" variant="primary" icon="upload" loading={uploading} disabled={!file}>
            Upload
          </Button>
        </div>
      </form>

      <ErrorBox error={error} />

      <div className="card">
        {loading ? (
          <Spinner label="Loading…" />
        ) : data.items.length === 0 ? (
          <p className="muted">No documents yet. Upload one above.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Source</th>
                <th>Type</th>
                <th>Size</th>
                <th>Added</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td className="muted">{d.source}</td>
                  <td>
                    <span className="badge">{d.metadata?.file_type}</span>
                  </td>
                  <td>{d.metadata?.byte_size != null ? `${(d.metadata.byte_size / 1024).toFixed(1)} KB` : ''}</td>
                  <td className="muted">{formatDate(d.created_at)}</td>
                  <td className="actions">
                    <Button size="sm" onClick={() => view(d.id)}>View</Button>{' '}
                    <Button size="sm" variant="ghost-danger" icon="trash" onClick={() => remove(d)} aria-label="Delete" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data.total > PAGE_SIZE && (
          <div className="pager">
            <Button size="sm" disabled={offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>Previous</Button>
            <span className="muted">Page {page} of {pages} ({data.total} documents)</span>
            <Button size="sm" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
          </div>
        )}
      </div>

      {viewing && (
        <div className="card">
          <div className="row between">
            <h2>{viewing.title}</h2>
            <Button size="sm" onClick={() => setViewing(null)}>Close</Button>
          </div>
          <pre className="doc-text">{viewing.content}</pre>
        </div>
      )}
    </>
  )
}
