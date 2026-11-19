import { useEffect, useId, useRef, useState } from 'react'
import Icon from '../Icon.jsx'

// A dropdown that looks like the rest of the app (the browser's <select> menu cannot be styled).
// Mouse: click to open, click an option. Keyboard: Enter, Space or the arrow keys open it; the
// arrows move, Enter picks, Escape closes, Home and End jump. `direction="up"` opens it above.
export default function Select({
  value,
  onChange,
  options, // [{ value, label, description? }]
  direction = 'down',
  size = 'md',
  id,
  'aria-label': ariaLabel,
  disabled = false,
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef(null)
  const list = useRef(null)
  const uid = useId()

  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value))
  const selected = options[selectedIndex]

  function openMenu() {
    if (disabled) return
    setActive(selectedIndex)
    setOpen(true)
  }
  function pick(index) {
    onChange(options[index].value)
    setOpen(false)
  }

  // Close on a click outside.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (!root.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  // Keep the highlighted option in view.
  useEffect(() => {
    if (open) list.current?.children[active]?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  function onKeyDown(e) {
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
        e.preventDefault()
        openMenu()
      }
      return
    }
    const last = options.length - 1
    if (e.key === 'ArrowDown') setActive((a) => Math.min(last, a + 1))
    else if (e.key === 'ArrowUp') setActive((a) => Math.max(0, a - 1))
    else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(last)
    else if (e.key === 'Enter' || e.key === ' ') pick(active)
    else if (e.key === 'Escape' || e.key === 'Tab') setOpen(false)
    else return
    e.preventDefault()
  }

  return (
    <div className={`select ${size} ${direction}`} ref={root}>
      <button
        type="button"
        id={id}
        className="select-trigger"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${uid}-list`}
        aria-activedescendant={open ? `${uid}-${active}` : undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onKeyDown}
      >
        <span className="select-value">{selected?.label}</span>
        <Icon name="chevron" size={16} />
      </button>
      {open && (
        <ul className="select-menu" role="listbox" id={`${uid}-list`} ref={list}>
          {options.map((o, i) => (
            <li
              key={o.value}
              id={`${uid}-${i}`}
              role="option"
              aria-selected={o.value === value}
              className={`${i === active ? 'active' : ''} ${o.value === value ? 'selected' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(i)}
            >
              <span>
                {o.label}
                {o.description && <span className="muted small option-desc">{o.description}</span>}
              </span>
              {o.value === value && <Icon name="check" size={16} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
