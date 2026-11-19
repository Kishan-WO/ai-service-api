import Select from './ui/Select.jsx'

export const BACKENDS = [
  { value: 'hosted', label: 'hosted (Gemini small)' },
  { value: 'hosted_large', label: 'hosted_large (Gemini large)' },
  { value: 'local', label: 'local (Ollama)' },
  { value: 'anthropic', label: 'anthropic' },
]

// Shows an ApiError: the message, the stable code, and the field errors of a 422.
export function ErrorBox({ error }) {
  if (!error) return null
  const fieldErrors = Array.isArray(error.details)
    ? error.details.map((d) => (typeof d === 'string' ? d : d.msg ?? JSON.stringify(d)))
    : []
  return (
    <div className="error" role="alert">
      <strong>{error.message}</strong>
      {error.code && <span className="code">{error.code}</span>}
      {fieldErrors.length > 0 && (
        <ul>
          {fieldErrors.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
      {error.requestId && <div className="muted">request id: {error.requestId}</div>}
    </div>
  )
}

export function BackendSelect({
  value,
  onChange,
  id,
  allowDefault = false,
  defaultLabel,
  direction = 'down',
  size = 'md',
}) {
  const options = [
    ...(allowDefault ? [{ value: '', label: defaultLabel ?? 'default' }] : []),
    ...BACKENDS,
  ]
  return (
    <Select
      id={id}
      aria-label="Model"
      value={value}
      onChange={onChange}
      options={options}
      direction={direction}
      size={size}
    />
  )
}

export function Spinner({ label = 'Working…' }) {
  return (
    <span className="spinner" role="status">
      <span className="dot" /> {label}
    </span>
  )
}

// A two-column table of label and value, for result metadata.
export function KeyValues({ rows }) {
  return (
    <table className="kv">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th>{k}</th>
            <td>{v === null || v === undefined ? <span className="muted">null</span> : String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function PageHeader({ title, children }) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {children && <p className="muted">{children}</p>}
    </header>
  )
}

export const formatDate = (iso) => new Date(iso).toLocaleString()
