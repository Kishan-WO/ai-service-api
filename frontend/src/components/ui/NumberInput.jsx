import Icon from '../Icon.jsx'

// A number field with minus and plus buttons (instead of the browser's tiny spinner arrows).
export default function NumberInput({ value, onChange, min = 0, max = 100, step = 1, 'aria-label': ariaLabel }) {
  const clamp = (n) => Math.min(max, Math.max(min, n))
  return (
    <div className="stepper">
      <button type="button" className="icon" onClick={() => onChange(clamp(value - step))} disabled={value <= min} aria-label="Decrease">
        <Icon name="minus" size={14} />
      </button>
      <input
        inputMode="numeric"
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, '')
          onChange(digits === '' ? min : clamp(Number(digits)))
        }}
      />
      <button type="button" className="icon" onClick={() => onChange(clamp(value + step))} disabled={value >= max} aria-label="Increase">
        <Icon name="plus" size={14} />
      </button>
    </div>
  )
}
