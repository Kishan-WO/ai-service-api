import Icon from '../Icon.jsx'

// A checkbox drawn by the app. The real <input> stays in the page (hidden but focusable), so the
// keyboard, screen readers and forms still work.
export default function Checkbox({ checked, onChange, children, disabled = false }) {
  return (
    <label className={`check${disabled ? ' disabled' : ''}`}>
      <input
        type="checkbox"
        className="check-input"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="check-box">
        <Icon name="check" size={14} />
      </span>
      {children && <span className="check-label">{children}</span>}
    </label>
  )
}
