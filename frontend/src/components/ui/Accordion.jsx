import { useState } from 'react'
import Icon from '../Icon.jsx'

// A section that opens and closes (instead of the browser's <details> triangle).
export default function Accordion({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`accordion${open ? ' open' : ''}`}>
      <button type="button" className="accordion-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{title}</span>
        <Icon name="chevron" size={18} />
      </button>
      <div className="accordion-body">
        <div>{children}</div>
      </div>
    </div>
  )
}
