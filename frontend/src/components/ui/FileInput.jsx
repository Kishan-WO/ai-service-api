import { useRef, useState } from 'react'
import Icon from '../Icon.jsx'

const size = (bytes) => (bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`)

// A drop zone instead of the browser's "Choose File | No file chosen" control.
export default function FileInput({ file, onChange, accept, hint }) {
  const input = useRef(null)
  const [over, setOver] = useState(false)

  function take(files) {
    const f = files?.[0]
    if (f) onChange(f)
  }
  function clear(e) {
    e.stopPropagation()
    onChange(null)
    if (input.current) input.current.value = ''
  }

  return (
    <div
      className={`filedrop${over ? ' over' : ''}${file ? ' has-file' : ''}`}
      role="button"
      tabIndex={0}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          input.current?.click()
        }
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        take(e.dataTransfer.files)
      }}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => take(e.target.files)}
      />
      <span className="filedrop-icon">
        <Icon name={file ? 'file' : 'upload'} size={20} />
      </span>
      {file ? (
        <span className="filedrop-text">
          <strong>{file.name}</strong>
          <span className="muted small">{size(file.size)}</span>
        </span>
      ) : (
        <span className="filedrop-text">
          <strong>Choose a file or drop it here</strong>
          {hint && <span className="muted small">{hint}</span>}
        </span>
      )}
      {file && (
        <button type="button" className="icon" onClick={clear} aria-label="Remove the file" title="Remove">
          <Icon name="close" size={16} />
        </button>
      )}
    </div>
  )
}
