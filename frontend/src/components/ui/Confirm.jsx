import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import Button from './Button.jsx'

// A confirmation dialog in the app's own style, replacing the browser's window.confirm().
//   const confirm = useConfirm()
//   if (await confirm({ title: 'Delete?', message: '...', confirmLabel: 'Delete', danger: true })) ...
const ConfirmContext = createContext(() => Promise.resolve(false))
export const useConfirm = () => useContext(ConfirmContext)

export function ConfirmProvider({ children }) {
  const [dialog, setDialog] = useState(null) // { options, resolve }
  const confirmButton = useRef(null)

  const confirm = useCallback(
    (options) => new Promise((resolve) => setDialog({ options, resolve })),
    [],
  )
  const close = (answer) => {
    dialog?.resolve(answer)
    setDialog(null)
  }

  useEffect(() => {
    if (!dialog) return
    confirmButton.current?.focus()
    const onKey = (e) => e.key === 'Escape' && close(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  })

  const o = dialog?.options
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {dialog && (
        <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && close(false)}>
          <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dialog-title">
            <h2 id="dialog-title">{o.title}</h2>
            {o.message && <p className="muted">{o.message}</p>}
            <div className="dialog-actions">
              <Button onClick={() => close(false)}>{o.cancelLabel ?? 'Cancel'}</Button>
              <Button
                ref={confirmButton}
                variant={o.danger ? 'danger-solid' : 'primary'}
                onClick={() => close(true)}
              >
                {o.confirmLabel ?? 'Confirm'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}
