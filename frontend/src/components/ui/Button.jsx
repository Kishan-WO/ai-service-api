import Icon from '../Icon.jsx'

// variant: primary | secondary | danger | ghost.  loading shows a spinner and disables the button.
export default function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  children,
  className = '',
  disabled,
  type = 'button',
  ...rest
}) {
  return (
    <button
      type={type}
      className={`btn ${variant} ${size} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <span className="btn-spin" aria-hidden="true" /> : icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  )
}
